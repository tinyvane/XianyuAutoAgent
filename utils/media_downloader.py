import os
import time
import asyncio
import aiohttp
from loguru import logger


# Content-Type → 文件扩展名映射
CONTENT_TYPE_EXT = {
    'image/jpeg': '.jpg',
    'image/png': '.png',
    'image/gif': '.gif',
    'image/webp': '.webp',
    'audio/mpeg': '.mp3',
    'audio/mp3': '.mp3',
    'audio/amr': '.amr',
    'audio/ogg': '.ogg',
    'video/mp4': '.mp4',
    'video/quicktime': '.mov',
}

# 媒体类型 → 默认扩展名
DEFAULT_EXT = {
    'image': '.jpg',
    'voice': '.mp3',
    'video': '.mp4',
}


class MediaDownloader:
    """异步媒体下载器，使用队列 + 后台 worker，不阻塞消息处理"""

    def __init__(self, context_manager, download_delay=0.5, max_workers=2):
        """
        Args:
            context_manager: ChatContextManager 实例
            download_delay: 每次下载间隔(秒)，防CDN限流
            max_workers: 并发下载数
        """
        self.ctx = context_manager
        self.download_delay = download_delay
        self.max_workers = max_workers
        self._queue = asyncio.Queue()
        self._tasks = []

    async def start(self):
        """启动后台下载 worker"""
        for i in range(self.max_workers):
            task = asyncio.create_task(self._worker(i))
            self._tasks.append(task)
        logger.info(f"MediaDownloader 已启动 ({self.max_workers} workers)")

    async def stop(self):
        """停止所有 worker"""
        for t in self._tasks:
            t.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks.clear()
        logger.info("MediaDownloader 已停止")

    async def enqueue(self, media_id, chat_id, media_type, url):
        """
        将下载任务入队

        Args:
            media_id: media_files 表的 ID
            chat_id: 会话ID
            media_type: 'image' / 'voice' / 'video'
            url: 下载URL
        """
        if not url:
            logger.warning(f"媒体URL为空，跳过下载: media_id={media_id}")
            return
        await self._queue.put({
            'media_id': media_id,
            'chat_id': chat_id,
            'media_type': media_type,
            'url': url,
        })
        logger.debug(f"下载任务已入队: media_id={media_id}, type={media_type}")

    async def _worker(self, worker_id):
        """后台下载 worker"""
        while True:
            try:
                item = await self._queue.get()
                try:
                    await self._download(item)
                except Exception as e:
                    logger.error(f"[worker-{worker_id}] 下载失败: {e}, media_id={item.get('media_id')}")
                    self.ctx.update_media_download(item['media_id'], None, status='failed')
                finally:
                    self._queue.task_done()
                    if self.download_delay > 0:
                        await asyncio.sleep(self.download_delay)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"[worker-{worker_id}] worker异常: {e}")
                await asyncio.sleep(1)

    async def _download(self, item):
        """执行单个文件下载"""
        media_id = item['media_id']
        chat_id = item['chat_id']
        media_type = item['media_type']
        url = item['url']

        # 标记为下载中
        self.ctx.update_media_download(media_id, None, status='downloading')

        media_dir = self.ctx.get_media_dir(chat_id, media_type)

        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=60)) as resp:
                if resp.status != 200:
                    logger.warning(f"下载失败 HTTP {resp.status}: {url}")
                    self.ctx.update_media_download(media_id, None, status='failed')
                    return

                # 从 Content-Type 检测扩展名
                ct = resp.headers.get('Content-Type', '').split(';')[0].strip().lower()
                ext = CONTENT_TYPE_EXT.get(ct, DEFAULT_EXT.get(media_type, ''))

                # 文件名: {timestamp}_{media_id}{ext}
                filename = f"{int(time.time() * 1000)}_{media_id}{ext}"
                filepath = os.path.join(media_dir, filename)

                data = await resp.read()
                with open(filepath, 'wb') as f:
                    f.write(data)

        # 计算相对路径（相对于 seller_root）
        if self.ctx.seller_root:
            rel_path = os.path.relpath(filepath, self.ctx.seller_root)
        else:
            rel_path = os.path.relpath(filepath, "data")

        file_size = os.path.getsize(filepath)
        self.ctx.update_media_download(media_id, rel_path, file_size=file_size, status='completed')
        logger.info(f"媒体文件已下载: {rel_path} ({file_size} bytes)")
