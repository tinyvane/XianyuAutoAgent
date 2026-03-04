import sqlite3
import os
import json
from datetime import datetime
from loguru import logger


class ChatContextManager:
    """
    聊天上下文管理器

    负责存储和检索用户与商品之间的对话历史，使用SQLite数据库进行持久化存储。
    支持按会话ID检索对话历史，以及议价次数统计。
    支持按卖家ID隔离数据（data/sellers/{seller_id}/）。
    """

    def __init__(self, max_history=100, db_path="data/chat_history.db", seller_id=None):
        """
        初始化聊天上下文管理器

        Args:
            max_history: 每个对话保留的最大消息数
            db_path: SQLite数据库文件路径（seller_id 为空时使用）
            seller_id: 卖家ID，设置后数据存储到 data/sellers/{seller_id}/
        """
        self.max_history = max_history
        self.seller_id = seller_id
        if seller_id:
            self.seller_root = os.path.join("data", "sellers", str(seller_id))
            self.db_path = os.path.join(self.seller_root, "chat_history.db")
        else:
            self.seller_root = None
            self.db_path = db_path
        self._init_db()
        
    def _init_db(self):
        """初始化数据库表结构"""
        # 确保数据库目录存在
        db_dir = os.path.dirname(self.db_path)
        if db_dir and not os.path.exists(db_dir):
            os.makedirs(db_dir)
            
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # 创建消息表
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL,
            item_id TEXT NOT NULL,
            role TEXT NOT NULL,
            content TEXT NOT NULL,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
            chat_id TEXT
        )
        ''')
        
        # 检查是否需要添加chat_id字段（兼容旧数据库）
        cursor.execute("PRAGMA table_info(messages)")
        columns = [column[1] for column in cursor.fetchall()]
        if 'chat_id' not in columns:
            cursor.execute('ALTER TABLE messages ADD COLUMN chat_id TEXT')
            logger.info("已为messages表添加chat_id字段")
        
        # 创建索引以加速查询
        cursor.execute('''
        CREATE INDEX IF NOT EXISTS idx_user_item ON messages (user_id, item_id)
        ''')
        
        cursor.execute('''
        CREATE INDEX IF NOT EXISTS idx_chat_id ON messages (chat_id)
        ''')
        
        cursor.execute('''
        CREATE INDEX IF NOT EXISTS idx_timestamp ON messages (timestamp)
        ''')
        
        # 创建基于会话ID的议价次数表
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS chat_bargain_counts (
            chat_id TEXT PRIMARY KEY,
            count INTEGER DEFAULT 0,
            last_updated DATETIME DEFAULT CURRENT_TIMESTAMP
        )
        ''')
        
        # 创建商品信息表
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS items (
            item_id TEXT PRIMARY KEY,
            data TEXT NOT NULL,
            price REAL,
            description TEXT,
            last_updated DATETIME DEFAULT CURRENT_TIMESTAMP
        )
        ''')

        # 创建媒体文件表
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS media_files (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            message_id INTEGER,
            chat_id TEXT NOT NULL,
            buyer_id TEXT,
            item_id TEXT,
            media_type TEXT NOT NULL,
            original_url TEXT,
            local_path TEXT,
            file_size INTEGER,
            download_status TEXT DEFAULT 'pending',
            metadata TEXT,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            downloaded_at DATETIME
        )
        ''')

        cursor.execute('''
        CREATE INDEX IF NOT EXISTS idx_media_chat ON media_files (chat_id)
        ''')

        # 迁移 messages 表：添加 content_type 和 media_file_id 列
        if 'content_type' not in columns:
            cursor.execute('ALTER TABLE messages ADD COLUMN content_type INTEGER DEFAULT 1')
            logger.info("已为messages表添加content_type字段")
        if 'media_file_id' not in columns:
            cursor.execute('ALTER TABLE messages ADD COLUMN media_file_id INTEGER')
            logger.info("已为messages表添加media_file_id字段")

        conn.commit()
        conn.close()
        logger.info(f"聊天历史数据库初始化完成: {self.db_path}")
        

            
    def save_item_info(self, item_id, item_data):
        """
        保存商品信息到数据库
        
        Args:
            item_id: 商品ID
            item_data: 商品信息字典
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        try:
            # 从商品数据中提取有用信息
            price = float(item_data.get('soldPrice', 0))
            description = item_data.get('desc', '')
            
            # 将整个商品数据转换为JSON字符串
            data_json = json.dumps(item_data, ensure_ascii=False)
            
            cursor.execute(
                """
                INSERT INTO items (item_id, data, price, description, last_updated) 
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(item_id) 
                DO UPDATE SET data = ?, price = ?, description = ?, last_updated = ?
                """,
                (
                    item_id, data_json, price, description, datetime.now().isoformat(),
                    data_json, price, description, datetime.now().isoformat()
                )
            )
            
            conn.commit()
            logger.debug(f"商品信息已保存: {item_id}")
        except Exception as e:
            logger.error(f"保存商品信息时出错: {e}")
            conn.rollback()
        finally:
            conn.close()
    
    def get_item_info(self, item_id):
        """
        从数据库获取商品信息
        
        Args:
            item_id: 商品ID
            
        Returns:
            dict: 商品信息字典，如果不存在返回None
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        try:
            cursor.execute(
                "SELECT data FROM items WHERE item_id = ?",
                (item_id,)
            )
            
            result = cursor.fetchone()
            if result:
                return json.loads(result[0])
            return None
        except Exception as e:
            logger.error(f"获取商品信息时出错: {e}")
            return None
        finally:
            conn.close()

    def add_message_by_chat(self, chat_id, user_id, item_id, role, content, content_type=1, media_file_id=None):
        """
        基于会话ID添加新消息到对话历史

        Args:
            chat_id: 会话ID
            user_id: 用户ID (用户消息存真实user_id，助手消息存卖家ID)
            item_id: 商品ID
            role: 消息角色 (user/assistant)
            content: 消息内容
            content_type: 内容类型 (1=文字, 2=图片, 3=语音, 4=视频)
            media_file_id: 关联的 media_files.id
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        try:
            # 插入新消息，使用chat_id作为额外标识
            cursor.execute(
                "INSERT INTO messages (user_id, item_id, role, content, timestamp, chat_id, content_type, media_file_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (user_id, item_id, role, content, datetime.now().isoformat(), chat_id, content_type, media_file_id)
            )
            
            # 检查是否需要清理旧消息（基于chat_id）
            cursor.execute(
                """
                SELECT id FROM messages 
                WHERE chat_id = ? 
                ORDER BY timestamp DESC 
                LIMIT ?, 1
                """, 
                (chat_id, self.max_history)
            )
            
            oldest_to_keep = cursor.fetchone()
            if oldest_to_keep:
                cursor.execute(
                    "DELETE FROM messages WHERE chat_id = ? AND id < ?",
                    (chat_id, oldest_to_keep[0])
                )
            
            conn.commit()
        except Exception as e:
            logger.error(f"添加消息到数据库时出错: {e}")
            conn.rollback()
        finally:
            conn.close()

    def get_context_by_chat(self, chat_id):
        """
        基于会话ID获取对话历史
        
        Args:
            chat_id: 会话ID
            
        Returns:
            list: 包含对话历史的列表
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        try:
            cursor.execute(
                """
                SELECT role, content FROM messages 
                WHERE chat_id = ? 
                ORDER BY timestamp ASC
                LIMIT ?
                """, 
                (chat_id, self.max_history)
            )
            
            messages = [{"role": role, "content": content} for role, content in cursor.fetchall()]
            
            # 获取议价次数并添加到上下文中
            bargain_count = self.get_bargain_count_by_chat(chat_id)
            if bargain_count > 0:
                messages.append({
                    "role": "system", 
                    "content": f"议价次数: {bargain_count}"
                })
            
        except Exception as e:
            logger.error(f"获取对话历史时出错: {e}")
            messages = []
        finally:
            conn.close()
        
        return messages

    def increment_bargain_count_by_chat(self, chat_id):
        """
        基于会话ID增加议价次数
        
        Args:
            chat_id: 会话ID
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        try:
            # 使用UPSERT语法直接基于chat_id增加议价次数
            cursor.execute(
                """
                INSERT INTO chat_bargain_counts (chat_id, count, last_updated)
                VALUES (?, 1, ?)
                ON CONFLICT(chat_id) 
                DO UPDATE SET count = count + 1, last_updated = ?
                """,
                (chat_id, datetime.now().isoformat(), datetime.now().isoformat())
            )
            
            conn.commit()
            logger.debug(f"会话 {chat_id} 议价次数已增加")
        except Exception as e:
            logger.error(f"增加议价次数时出错: {e}")
            conn.rollback()
        finally:
            conn.close()

    def get_bargain_count_by_chat(self, chat_id):
        """
        基于会话ID获取议价次数
        
        Args:
            chat_id: 会话ID
            
        Returns:
            int: 议价次数
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        try:
            cursor.execute(
                "SELECT count FROM chat_bargain_counts WHERE chat_id = ?",
                (chat_id,)
            )
            
            result = cursor.fetchone()
            return result[0] if result else 0
        except Exception as e:
            logger.error(f"获取议价次数时出错: {e}")
            return 0
        finally:
            conn.close()

    # ── 媒体文件相关方法 ──

    def get_media_dir(self, chat_id, media_type):
        """
        获取并创建媒体目录

        Args:
            chat_id: 会话ID
            media_type: 媒体类型 ('image'/'voice'/'video')

        Returns:
            str: 媒体目录的绝对路径
        """
        type_dir_map = {'image': 'images', 'voice': 'voice', 'video': 'video'}
        sub_dir = type_dir_map.get(media_type, media_type)

        if self.seller_root:
            media_dir = os.path.join(self.seller_root, "media", str(chat_id), sub_dir)
        else:
            media_dir = os.path.join("data", "media", str(chat_id), sub_dir)

        os.makedirs(media_dir, exist_ok=True)
        return media_dir

    def save_media_record(self, chat_id, media_type, original_url, buyer_id=None, item_id=None, metadata=None):
        """
        保存媒体索引记录

        Args:
            chat_id: 会话ID
            media_type: 'image' / 'voice' / 'video'
            original_url: 原始URL
            buyer_id: 买家ID
            item_id: 商品ID
            metadata: 附加元数据(dict)

        Returns:
            int: 新记录的ID
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        try:
            meta_json = json.dumps(metadata, ensure_ascii=False) if metadata else None
            cursor.execute(
                """INSERT INTO media_files
                   (chat_id, buyer_id, item_id, media_type, original_url, metadata)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (chat_id, buyer_id, item_id, media_type, original_url, meta_json)
            )
            conn.commit()
            media_id = cursor.lastrowid
            logger.debug(f"媒体记录已保存: id={media_id}, type={media_type}, chat={chat_id}")
            return media_id
        except Exception as e:
            logger.error(f"保存媒体记录失败: {e}")
            conn.rollback()
            return None
        finally:
            conn.close()

    def update_media_download(self, media_id, local_path, file_size=None, status='completed'):
        """
        下载完成后更新媒体记录

        Args:
            media_id: media_files.id
            local_path: 相对于 seller_root 的本地路径
            file_size: 文件大小 (bytes)
            status: 下载状态
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        try:
            cursor.execute(
                """UPDATE media_files
                   SET local_path = ?, file_size = ?, download_status = ?, downloaded_at = ?
                   WHERE id = ?""",
                (local_path, file_size, status, datetime.now().isoformat(), media_id)
            )
            conn.commit()
            logger.debug(f"媒体下载状态已更新: id={media_id}, status={status}")
        except Exception as e:
            logger.error(f"更新媒体下载状态失败: {e}")
            conn.rollback()
        finally:
            conn.close()

    def get_chat_media(self, chat_id, media_type=None):
        """
        查询某会话的所有媒体文件

        Args:
            chat_id: 会话ID
            media_type: 可选过滤媒体类型

        Returns:
            list[dict]: 媒体记录列表
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        try:
            if media_type:
                cursor.execute(
                    "SELECT * FROM media_files WHERE chat_id = ? AND media_type = ? ORDER BY created_at",
                    (chat_id, media_type)
                )
            else:
                cursor.execute(
                    "SELECT * FROM media_files WHERE chat_id = ? ORDER BY created_at",
                    (chat_id,)
                )

            columns = [desc[0] for desc in cursor.description]
            return [dict(zip(columns, row)) for row in cursor.fetchall()]
        except Exception as e:
            logger.error(f"查询媒体记录失败: {e}")
            return []
        finally:
            conn.close()