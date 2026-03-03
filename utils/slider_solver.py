"""
Baxia 滑块自动解决器

闲鱼的 Baxia 风控滑块是简单的"拖到最右边"类型，不需要图像识别。
通过 Playwright 模拟人类鼠标轨迹完成拖拽操作。
"""

import asyncio
import random
import os

from loguru import logger


# 滑块 iframe 内的布局常量（基于实际观察）
SLIDER_BUTTON_X_OFFSET = 40   # 滑块按钮距 iframe 左边的偏移
SLIDER_BUTTON_Y_OFFSET = 240  # 滑块按钮距 iframe 顶部的偏移
SLIDER_TRACK_WIDTH = 340       # 滑轨宽度（约）
SLIDER_BUTTON_WIDTH = 40       # 滑块按钮宽度（约）

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
        # 二次加速曲线
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
        # 减速曲线: 1 - (1-t)^2
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
    """检测页面上是否存在 Baxia 滑块对话框。返回 iframe 的 bounding rect 或 None。"""
    try:
        # 等待一下让页面渲染
        await asyncio.sleep(1)

        # 检测 baxia-dialog 容器
        dialog = await page.query_selector('.baxia-dialog')
        if not dialog:
            dialog = await page.query_selector('#baxia-dialog')
        if not dialog:
            return None

        logger.info("检测到 Baxia 滑块对话框")

        # 获取 iframe 元素
        iframe = await page.query_selector('#baxia-dialog-content')
        if not iframe:
            iframe = await page.query_selector('.baxia-dialog iframe')

        if not iframe:
            logger.warning("找到 baxia-dialog 但未找到 iframe")
            return None

        # 获取 iframe 在 viewport 中的位置
        rect = await iframe.bounding_box()
        if not rect:
            logger.warning("无法获取 iframe 的 bounding box")
            return None

        logger.info(f"Baxia iframe 位置: x={rect['x']}, y={rect['y']}, "
                     f"w={rect['width']}, h={rect['height']}")
        return rect

    except Exception as e:
        logger.error(f"检测滑块时出错: {e}")
        return None


async def solve_slider(page, iframe_rect):
    """
    解决滑块验证。

    Args:
        page: Playwright page 对象
        iframe_rect: iframe 的 bounding box dict (x, y, width, height)

    Returns:
        bool: 是否成功解决
    """
    try:
        # 计算滑块按钮在 viewport 中的绝对坐标
        btn_x = iframe_rect['x'] + SLIDER_BUTTON_X_OFFSET
        btn_y = iframe_rect['y'] + SLIDER_BUTTON_Y_OFFSET

        # 计算需要拖拽的距离（拖到最右边）
        drag_distance = iframe_rect['width'] - SLIDER_BUTTON_X_OFFSET - SLIDER_BUTTON_WIDTH // 2

        logger.info(f"滑块起始位置: ({btn_x}, {btn_y}), 拖拽距离: {drag_distance}px")

        # 先移动到滑块按钮上方附近，模拟人类先定位
        approach_x = btn_x + random.uniform(-5, 5)
        approach_y = btn_y + random.uniform(-20, -10)
        await page.mouse.move(approach_x, approach_y)
        await asyncio.sleep(random.uniform(0.2, 0.5))

        # 移动到滑块按钮中心
        await page.mouse.move(btn_x, btn_y)
        await asyncio.sleep(random.uniform(0.1, 0.3))

        # 按下鼠标
        await page.mouse.down()
        await asyncio.sleep(random.uniform(0.05, 0.15))

        # 生成并执行人类轨迹
        trajectory = generate_human_trajectory(btn_x, btn_y, drag_distance)

        for x, y, delay_ms in trajectory:
            await page.mouse.move(x, y)
            await asyncio.sleep(delay_ms / 1000.0)

        # 释放鼠标前短暂停顿
        await asyncio.sleep(random.uniform(0.05, 0.15))
        await page.mouse.up()

        logger.info("滑块拖拽完成，等待验证结果...")

        # 等待验证结果：baxia-dialog 消失 = 成功
        for _ in range(30):  # 最多等待 3 秒
            await asyncio.sleep(0.1)
            dialog = await page.query_selector('.baxia-dialog')
            if not dialog:
                logger.success("滑块验证成功！对话框已消失")
                return True
            # 也检查是否变为 hidden
            visible = await dialog.is_visible()
            if not visible:
                logger.success("滑块验证成功！对话框已隐藏")
                return True

        logger.warning("滑块验证可能失败，对话框未消失")
        return False

    except Exception as e:
        logger.error(f"解决滑块时出错: {e}")
        return False


async def attempt_solve_slider(page):
    """
    检测并尝试解决滑块，带重试机制。

    Args:
        page: Playwright page 对象

    Returns:
        bool: 是否成功解决（如果没有滑块也返回 True）
    """
    iframe_rect = await detect_baxia_slider(page)
    if not iframe_rect:
        logger.info("未检测到滑块，无需解决")
        return True

    for attempt in range(1, MAX_ATTEMPTS + 1):
        logger.info(f"第 {attempt}/{MAX_ATTEMPTS} 次尝试解决滑块...")

        # 每次重试前重新检测位置（可能变化）
        if attempt > 1:
            await asyncio.sleep(random.uniform(1.0, 2.0))
            iframe_rect = await detect_baxia_slider(page)
            if not iframe_rect:
                logger.info("滑块已消失，可能已自动恢复")
                return True

        success = await solve_slider(page, iframe_rect)
        if success:
            return True

        logger.warning(f"第 {attempt} 次尝试失败")

    logger.error(f"滑块解决失败，已尝试 {MAX_ATTEMPTS} 次")
    return False
