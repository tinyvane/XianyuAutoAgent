"""
Baxia 滑块自动解决器

闲鱼的 Baxia 风控滑块是简单的"拖到最右边"类型，不需要图像识别。
通过 Playwright 模拟人类鼠标轨迹完成拖拽操作。

关键技术：通过 CDP 连接可以访问跨域 iframe 内部 DOM，
直接获取滑块按钮 (#nc_1_n1z) 和滑轨 (.nc_scale) 的精确坐标。
"""

import asyncio
import random
import os

from loguru import logger


MAX_ATTEMPTS = int(os.getenv("SLIDER_MAX_ATTEMPTS", "3"))


def generate_human_trajectory(start_x, start_y, distance):
    """
    生成仿人类的鼠标拖拽轨迹。

    模拟真实人类拖拽行为：
    - 加速启动
    - 匀速滑动
    - 接近终点减速
    - 微小过冲
    - 回调修正

    Returns:
        list of (x, y, delay_ms) 元组
    """
    points = []

    # 阶段1: 加速 (0-30% 距离)
    phase1_end = distance * 0.3
    phase1_steps = random.randint(8, 12)
    for i in range(phase1_steps):
        progress = (i + 1) / phase1_steps
        x_offset = phase1_end * (progress ** 2)
        y_jitter = random.uniform(-1.5, 1.5)
        delay = random.randint(8, 18)
        points.append((start_x + x_offset, start_y + y_jitter, delay))

    # 阶段2: 匀速 (30-75% 距离)
    phase2_start = phase1_end
    phase2_end = distance * 0.75
    phase2_distance = phase2_end - phase2_start
    phase2_steps = random.randint(10, 16)
    for i in range(phase2_steps):
        progress = (i + 1) / phase2_steps
        x_offset = phase2_start + phase2_distance * progress
        y_jitter = random.uniform(-2.0, 2.0)
        delay = random.randint(6, 14)
        points.append((start_x + x_offset, start_y + y_jitter, delay))

    # 阶段3: 减速 (75-100% 距离)
    phase3_start = phase2_end
    phase3_distance = distance - phase3_start
    phase3_steps = random.randint(8, 14)
    for i in range(phase3_steps):
        progress = (i + 1) / phase3_steps
        eased = 1 - (1 - progress) ** 2
        x_offset = phase3_start + phase3_distance * eased
        y_jitter = random.uniform(-1.0, 1.0)
        delay = random.randint(12, 28)
        points.append((start_x + x_offset, start_y + y_jitter, delay))

    # 阶段4: 过冲 (超过目标 3-8px)
    overshoot = random.uniform(3, 8)
    overshoot_steps = random.randint(2, 4)
    for i in range(overshoot_steps):
        progress = (i + 1) / overshoot_steps
        x_offset = distance + overshoot * progress
        y_jitter = random.uniform(-0.5, 0.5)
        delay = random.randint(10, 20)
        points.append((start_x + x_offset, start_y + y_jitter, delay))

    # 阶段5: 回调修正 (回到精确位置)
    correction_steps = random.randint(2, 4)
    current_x = distance + overshoot
    for i in range(correction_steps):
        progress = (i + 1) / correction_steps
        x_offset = current_x - overshoot * progress
        y_jitter = random.uniform(-0.3, 0.3)
        delay = random.randint(15, 30)
        points.append((start_x + x_offset, start_y + y_jitter, delay))

    return points


async def detect_baxia_slider(page):
    """
    检测页面上是否存在 Baxia 滑块对话框。

    Returns:
        dict with 'btn_box', 'track_box', 'iframe_el' or None
    """
    try:
        await asyncio.sleep(1)

        # 检测 baxia-dialog 容器
        dialog = await page.query_selector('.baxia-dialog')
        if not dialog:
            dialog = await page.query_selector('#baxia-dialog')
        if not dialog:
            return None

        visible = await dialog.is_visible()
        if not visible:
            return None

        logger.info("检测到 Baxia 滑块对话框")

        # 获取 iframe 元素
        iframe_el = await page.query_selector('#baxia-dialog-content')
        if not iframe_el:
            iframe_el = await page.query_selector('.baxia-dialog iframe')
        if not iframe_el:
            logger.warning("找到 baxia-dialog 但未找到 iframe")
            return None

        # 尝试通过 CDP 访问 iframe 内部 DOM（精确定位）
        frame = await iframe_el.content_frame()
        if frame:
            # 查找滑块按钮
            btn = await frame.query_selector('#nc_1_n1z')
            if not btn:
                btn = await frame.query_selector('.btn_slide')
            # 查找滑轨
            track = await frame.query_selector('.nc_scale')
            if not track:
                track = await frame.query_selector('#nc_1__scale_text')

            if btn and track:
                btn_box = await btn.bounding_box()
                track_box = await track.bounding_box()
                if btn_box and track_box:
                    logger.info(f"滑块按钮: x={btn_box['x']:.0f}, y={btn_box['y']:.0f}, "
                                f"w={btn_box['width']:.0f}, h={btn_box['height']:.0f}")
                    logger.info(f"滑轨: x={track_box['x']:.0f}, y={track_box['y']:.0f}, "
                                f"w={track_box['width']:.0f}")
                    return {
                        'btn_box': btn_box,
                        'track_box': track_box,
                        'iframe_el': iframe_el,
                        'frame': frame,
                    }

            logger.warning("iframe 内未找到滑块按钮或滑轨元素")

        # 降级：使用 iframe 位置 + 硬编码偏移
        logger.info("降级到硬编码偏移模式")
        iframe_rect = await iframe_el.bounding_box()
        if not iframe_rect:
            return None

        btn_box = {
            'x': iframe_rect['x'] + 62,
            'y': iframe_rect['y'] + 200,
            'width': 42,
            'height': 30,
        }
        track_box = {
            'x': iframe_rect['x'] + 60,
            'y': iframe_rect['y'] + 200,
            'width': 300,
            'height': 34,
        }
        return {
            'btn_box': btn_box,
            'track_box': track_box,
            'iframe_el': iframe_el,
            'frame': None,
        }

    except Exception as e:
        logger.error(f"检测滑块时出错: {e}")
        return None


async def solve_slider(page, slider_info):
    """
    解决滑块验证。

    Args:
        page: Playwright page 对象
        slider_info: detect_baxia_slider 返回的 dict

    Returns:
        bool: 是否成功解决
    """
    try:
        btn_box = slider_info['btn_box']
        track_box = slider_info['track_box']

        # 滑块按钮中心坐标
        btn_center_x = btn_box['x'] + btn_box['width'] / 2
        btn_center_y = btn_box['y'] + btn_box['height'] / 2

        # 拖拽距离 = 滑轨右边界 - 按钮中心
        track_right = track_box['x'] + track_box['width']
        drag_distance = track_right - btn_center_x - btn_box['width'] / 2

        logger.info(f"按钮中心: ({btn_center_x:.0f}, {btn_center_y:.0f}), "
                    f"拖拽距离: {drag_distance:.0f}px")

        # 先移动到滑块按钮上方附近
        approach_x = btn_center_x + random.uniform(-5, 5)
        approach_y = btn_center_y + random.uniform(-20, -10)
        await page.mouse.move(approach_x, approach_y)
        await asyncio.sleep(random.uniform(0.2, 0.5))

        # 移动到滑块按钮中心
        await page.mouse.move(btn_center_x, btn_center_y)
        await asyncio.sleep(random.uniform(0.1, 0.3))

        # 按下鼠标
        await page.mouse.down()
        await asyncio.sleep(random.uniform(0.05, 0.15))

        # 生成并执行人类轨迹
        trajectory = generate_human_trajectory(btn_center_x, btn_center_y, drag_distance)

        for x, y, delay_ms in trajectory:
            await page.mouse.move(x, y)
            await asyncio.sleep(delay_ms / 1000.0)

        # 释放鼠标前短暂停顿
        await asyncio.sleep(random.uniform(0.05, 0.15))
        await page.mouse.up()

        logger.info("滑块拖拽完成，等待验证结果...")

        # 记录当前 URL
        original_url = page.url

        # 等待验证结果（最多 10 秒）
        for i in range(100):
            await asyncio.sleep(0.1)

            # 检查页面是否刷新/导航
            if page.url != original_url:
                logger.success("滑块验证成功！页面已导航")
                return True

            try:
                # 检查 baxia-dialog 是否消失或隐藏
                dialog = await page.query_selector('.baxia-dialog')
                if not dialog:
                    logger.success("滑块验证成功！对话框已消失")
                    return True
                visible = await dialog.is_visible()
                if not visible:
                    logger.success("滑块验证成功！对话框已隐藏")
                    return True

                # 检查 iframe 内部状态（如果可访问）
                frame = slider_info.get('frame')
                if frame:
                    try:
                        # 验证成功后滑块可能变为绿色/显示成功状态
                        success_el = await frame.query_selector('.nc-lang-cnt[data-nc-lang="_yesTEXT"]')
                        if success_el:
                            logger.success("滑块验证成功！检测到成功状态元素")
                            return True
                        # 检查滑块按钮是否还存在（成功后可能被移除）
                        btn = await frame.query_selector('#nc_1_n1z')
                        if not btn:
                            logger.success("滑块验证成功！按钮已移除")
                            return True
                    except Exception:
                        pass

                # 检查 iframe 是否被移除
                iframe = await page.query_selector('#baxia-dialog-content')
                if not iframe:
                    logger.success("滑块验证成功！iframe 已移除")
                    return True
            except Exception:
                # 页面可能正在刷新/导航
                logger.success("滑块验证成功！页面正在刷新")
                return True

        logger.warning("滑块验证超时，对话框未消失")
        return False

    except Exception as e:
        logger.error(f"解决滑块时出错: {e}")
        return False


async def attempt_solve_slider(page):
    """
    检测并尝试解决滑块，带重试机制。

    Returns:
        bool: 是否成功解决（如果没有滑块也返回 True）
    """
    slider_info = await detect_baxia_slider(page)
    if not slider_info:
        logger.info("未检测到滑块，无需解决")
        return True

    for attempt in range(1, MAX_ATTEMPTS + 1):
        logger.info(f"第 {attempt}/{MAX_ATTEMPTS} 次尝试解决滑块...")

        # 每次重试前重新检测位置（可能变化）
        if attempt > 1:
            await asyncio.sleep(random.uniform(1.0, 2.0))
            slider_info = await detect_baxia_slider(page)
            if not slider_info:
                logger.info("滑块已消失，可能已自动恢复")
                return True

        success = await solve_slider(page, slider_info)
        if success:
            return True

        logger.warning(f"第 {attempt} 次尝试失败")

    logger.error(f"滑块解决失败，已尝试 {MAX_ATTEMPTS} 次")
    return False
