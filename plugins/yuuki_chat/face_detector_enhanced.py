"""
人脸检测工具（增强版 v2）

功能：
- 多源输入：图片 / 摄像头 / 视频 / URL
- 多特征检测：人脸 / 眼睛 / 鼻子 / 嘴巴 / 微笑 / 侧脸
- DNN人脸检测（更准确，需OpenCV>=4.5）
- 多尺度检测（大图自动缩放加速）
- NMS去重（消除重叠检测框）
- 人脸马赛克/模糊（隐私保护）
- 人脸裁剪保存
- 实时FPS + 平滑显示
- 检测结果JSON导出
- 进度条（视频模式）
- 无头模式（服务器环境自动跳过显示）

依赖：pip install opencv-python numpy
"""

import cv2 as cv
import numpy as np
import sys
import os
import time
import json
import urllib.request
from datetime import datetime

# ========== 配置 ==========
CASCADE_DIR = "cascade_files"

# 级联分类器文件
_CASCADE_FILES = {
    "face_frontal": os.path.join(CASCADE_DIR, "haarcascade_frontalface_alt.xml"),
    "face_profile": os.path.join(CASCADE_DIR, "haarcascade_profileface.xml"),
    "eye": os.path.join(CASCADE_DIR, "haarcascade_eye.xml"),
    "nose": os.path.join(CASCADE_DIR, "haarcascade_mcs_nose.xml"),
    "smile": os.path.join(CASCADE_DIR, "haarcascade_smile.xml"),
    "mouth": os.path.join(CASCADE_DIR, "haarcascade_mcs_mouth.xml"),
}

# DNN模型
_DNN_PROTO = "deploy.prototxt"
_DNN_MODEL = "res10_300x300_ssd_iter_140000.caffemodel"

# 检测参数
SCALE_FACTOR = 1.3
MIN_NEIGHBORS = 5
MIN_FACE_SIZE = (30, 30)
DNN_CONFIDENCE = 0.7

# NMS参数
NMS_IOU_THRESHOLD = 0.3  # IoU阈值，低于此值保留两个框

# 多尺度阈值
MULTI_SCALE_THRESHOLD = 800

# 显示参数
MAX_DISPLAY_W = 900
MAX_DISPLAY_H = 700

# 颜色 (BGR)
C_FACE = (0, 0, 255)         # 红色 - 人脸框
C_FACE_PROFILE = (0, 128, 255)  # 橙色 - 侧脸框
C_EYE = (255, 0, 0)         # 蓝色 - 眼睛
C_NOSE = (0, 255, 0)        # 绿色 - 鼻子
C_SMILE = (0, 255, 255)     # 黄色 - 微笑
C_MOUTH = (255, 165, 0)     # 橙色 - 嘴巴
C_TEXT = (255, 255, 255)     # 白色 - 文字
C_BG = (40, 40, 40)         # 信息栏背景

# 检测是否支持GUI显示
_HEADLESS = os.environ.get("DISPLAY", "") == "" and sys.platform == "linux"


# ========== 工具函数 ==========

def download_file(url, save_path):
    """从URL下载文件"""
    try:
        urllib.request.urlretrieve(url, save_path)
        return True
    except Exception as e:
        print(f"[错误] 下载失败: {e}")
        return False


def load_cascade(path, name):
    """加载级联分类器，失败返回None"""
    if not os.path.exists(path):
        print(f"[警告] 找不到{name}分类器: {path}，跳过")
        return None
    c = cv.CascadeClassifier(path)
    if c.empty():
        print(f"[警告] {name}分类器加载失败，跳过")
        return None
    return c


def resize_for_display(frame):
    """缩放以适应显示窗口"""
    h, w = frame.shape[:2]
    if w > MAX_DISPLAY_W or h > MAX_DISPLAY_H:
        s = min(MAX_DISPLAY_W / w, MAX_DISPLAY_H / h)
        return cv.resize(frame, (int(w * s), int(h * s)))
    return frame


def draw_info_bar(frame, text, y_offset=0):
    """在画面顶部绘制半透明信息栏"""
    h, w = frame.shape[:2]
    bar_h = 35
    overlay = frame.copy()
    cv.rectangle(overlay, (0, y_offset), (w, y_offset + bar_h), C_BG, -1)
    cv.addWeighted(overlay, 0.6, frame, 0.4, 0, frame)
    cv.putText(frame, text, (12, y_offset + 25), cv.FONT_HERSHEY_SIMPLEX, 0.65, C_TEXT, 2)
    return frame


def draw_progress_bar(frame, current, total, y_offset=40):
    """绘制进度条"""
    h, w = frame.shape[:2]
    bar_h = 12
    progress = current / max(total, 1)
    cv.rectangle(frame, (0, y_offset), (w, y_offset + bar_h), (60, 60, 60), -1)
    cv.rectangle(frame, (0, y_offset), (int(w * progress), y_offset + bar_h), (0, 180, 255), -1)
    pct_text = f"{current}/{total} ({progress*100:.0f}%)"
    cv.putText(frame, pct_text, (w - 160, y_offset + 10), cv.FONT_HERSHEY_SIMPLEX, 0.45, C_TEXT, 1)


def nms(boxes, iou_threshold=NMS_IOU_THRESHOLD):
    """非极大值抑制，去除重叠检测框

    Args:
        boxes: [(x, y, w, h, confidence), ...]
        iou_threshold: IoU阈值

    Returns:
        过滤后的boxes列表
    """
    if len(boxes) <= 1:
        return boxes

    # 按置信度降序排序
    boxes = sorted(boxes, key=lambda b: b[4], reverse=True)

    keep = []
    while boxes:
        best = boxes.pop(0)
        keep.append(best)
        boxes = [b for b in boxes if _iou(best, b) < iou_threshold]

    return keep


def _iou(box_a, box_b):
    """计算两个框的IoU"""
    ax, ay, aw, ah, _ = box_a
    bx, by, bw, bh, _ = box_b

    # 计算交集
    x1 = max(ax, bx)
    y1 = max(ay, by)
    x2 = min(ax + aw, bx + bw)
    y2 = min(ay + ah, by + bh)

    intersection = max(0, x2 - x1) * max(0, y2 - y1)
    union = aw * ah + bw * bh - intersection

    return intersection / union if union > 0 else 0


def safe_show(winname, frame):
    """安全显示（无头环境跳过）"""
    if _HEADLESS:
        return
    try:
        cv.imshow(winname, frame)
    except cv.error:
        pass


def safe_wait_key(delay=0):
    """安全等待按键（无头环境跳过）"""
    if _HEADLESS:
        return -1
    try:
        return cv.waitKey(delay) & 0xFF
    except cv.error:
        return -1


def safe_destroy():
    """安全销毁窗口"""
    try:
        cv.destroyAllWindows()
    except cv.error:
        pass


# ========== 检测器 ==========

class FaceDetector:
    """人脸检测器（支持Haar + DNN双引擎）"""

    def __init__(self, use_dnn=False, detect_nose=True, detect_eyes=False,
                 detect_smile=False, detect_mouth=True, detect_profile=False):
        self.use_dnn = use_dnn
        self.detect_nose = detect_nose
        self.detect_eyes = detect_eyes
        self.detect_smile = detect_smile
        self.detect_mouth = detect_mouth
        self.detect_profile = detect_profile

        # Haar级联分类器
        self.face_cascade = load_cascade(_CASCADE_FILES["face_frontal"], "人脸(正面)")
        self.profile_cascade = load_cascade(_CASCADE_FILES["face_profile"], "人脸(侧脸)") if detect_profile else None
        self.eye_cascade = load_cascade(_CASCADE_FILES["eye"], "眼睛") if detect_eyes else None
        self.nose_cascade = load_cascade(_CASCADE_FILES["nose"], "鼻子") if detect_nose else None
        self.smile_cascade = load_cascade(_CASCADE_FILES["smile"], "微笑") if detect_smile else None
        self.mouth_cascade = load_cascade(_CASCADE_FILES["mouth"], "嘴部") if detect_mouth else None

        # DNN模型
        self.dnn_net = None
        if use_dnn:
            if os.path.exists(_DNN_MODEL) and os.path.exists(_DNN_PROTO):
                self.dnn_net = cv.dnn.readNetFromCaffe(_DNN_PROTO, _DNN_MODEL)
                print("[OK] DNN人脸检测模型已加载")
            else:
                print("[警告] DNN模型文件不存在，回退到Haar级联")
                self.use_dnn = False

        # FPS平滑
        self._fps_history = []
        self._last_time = time.time()

    def _smooth_fps(self):
        """计算平滑FPS"""
        now = time.time()
        dt = now - self._last_time
        self._last_time = now
        if dt > 0:
            self._fps_history.append(1.0 / dt)
        if len(self._fps_history) > 30:
            self._fps_history.pop(0)
        return np.mean(self._fps_history) if self._fps_history else 0

    def detect(self, frame):
        """检测人脸及特征，返回 (标注帧, 人脸列表)

        人脸列表按从左到右排序，每个元素为dict:
        {
            "bbox": [x, y, w, h],
            "confidence": float,
            "eyes": [[x,y,w,h], ...],
            "nose": [x,y,w,h] or None,
            "mouth": [x,y,w,h] or None,
            "smile": bool
        }
        """
        h, w = frame.shape[:2]
        gray = cv.cvtColor(frame, cv.COLOR_BGR2GRAY)
        gray = cv.equalizeHist(gray)

        faces = []
        scale = 1.0

        # 多尺度优化：大图先缩小检测，再映射回原图
        small_gray = gray
        if w > MULTI_SCALE_THRESHOLD:
            scale = MULTI_SCALE_THRESHOLD / w
            small_gray = cv.resize(gray, (int(w * scale), int(h * scale)))

        # ---- 人脸检测 ----
        if self.use_dnn and self.dnn_net:
            faces = self._detect_dnn(small_gray, scale)
        else:
            faces = self._detect_haar(small_gray, scale)

        # ---- NMS去重 ----
        faces = nms(faces)

        # ---- 按从左到右排序 ----
        faces.sort(key=lambda f: f[0])

        # ---- 特征检测 ----
        results = []
        for (fx, fy, fw, fh, conf) in faces:
            # 映射回原图坐标
            ox, oy, ow, oh = int(fx / scale), int(fy / scale), int(fw / scale), int(fh / scale)
            oy = max(0, oy)
            oh = min(h - oy, oh)
            ox = max(0, ox)
            ow = min(w - ox, ow)

            face_info = {
                "bbox": [ox, oy, ow, oh],
                "confidence": round(conf, 3),
                "eyes": [], "nose": None, "mouth": None, "smile": False
            }

            roi_gray = gray[oy:oy + oh, ox:ox + ow]
            roi_color = frame[oy:oy + oh, ox:ox + ow]

            # 眼睛（最多2只）
            if self.eye_cascade:
                eyes = self.eye_cascade.detectMultiScale(roi_gray, 1.3, 5)
                for (ex, ey, ew, eh) in eyes[:2]:
                    cv.rectangle(roi_color, (ex, ey), (ex + ew, ey + eh), C_EYE, 2)
                    face_info["eyes"].append([ex, ey, ew, eh])

            # 鼻子（取置信度最高的1个）
            if self.nose_cascade:
                noses = self.nose_cascade.detectMultiScale(roi_gray, 1.3, 5)
                if len(noses) > 0:
                    # 取面积最大的（通常是正确的鼻子）
                    best = max(noses, key=lambda n: n[2] * n[3])
                    nx, ny, nw, nh = best
                    cv.rectangle(roi_color, (nx, ny), (nx + nw, ny + nh), C_NOSE, 2)
                    face_info["nose"] = [nx, ny, nw, nh]

            # 嘴巴（取面积最大的1个）
            if self.mouth_cascade:
                mouths = self.mouth_cascade.detectMultiScale(roi_gray, 1.3, 20, minSize=(30, 15))
                if len(mouths) > 0:
                    best = max(mouths, key=lambda m: m[2] * m[3])
                    mx, my, mw, mh = best
                    cv.rectangle(roi_color, (mx, my), (mx + mw, my + mh), C_MOUTH, 2)
                    face_info["mouth"] = [mx, my, mw, mh]

            # 微笑
            if self.smile_cascade:
                smiles = self.smile_cascade.detectMultiScale(roi_gray, 1.3, 20, minSize=(25, 25))
                if len(smiles) > 0:
                    face_info["smile"] = True
                    cv.putText(frame, "Smile!", (ox, oy + oh + 22),
                               cv.FONT_HERSHEY_SIMPLEX, 0.6, C_SMILE, 2)

            results.append(face_info)

        return frame, results

    def _detect_haar(self, gray, scale):
        """Haar级联检测"""
        faces = []
        if self.face_cascade:
            detected = self.face_cascade.detectMultiScale(
                gray, SCALE_FACTOR, MIN_NEIGHBORS, minSize=MIN_FACE_SIZE
            )
            for (x, y, w, h) in detected:
                faces.append((x, y, w, h, 1.0))

        # 侧脸
        if self.profile_cascade:
            detected = self.profile_cascade.detectMultiScale(
                gray, SCALE_FACTOR, MIN_NEIGHBORS, minSize=MIN_FACE_SIZE
            )
            for (x, y, w, h) in detected:
                faces.append((x, y, w, h, 0.9))

        return faces

    def _detect_dnn(self, frame, scale):
        """DNN CNN人脸检测"""
        h, w = frame.shape[:2]
        blob = cv.dnn.blobFromImage(cv.resize(frame, (300, 300)), 1.0,
                                     (300, 300), (104.0, 177.0, 123.0))
        self.dnn_net.setInput(blob)
        detections = self.dnn_net.forward()

        faces = []
        for i in range(detections.shape[2]):
            confidence = detections[0, 0, i, 2]
            if confidence > DNN_CONFIDENCE:
                box = detections[0, 0, i, 3:7] * np.array([w, h, w, h])
                (x1, y1, x2, y2) = box.astype("int")
                x1, y1 = max(0, x1), max(0, y1)
                faces.append((x1, y1, x2 - x1, y2 - y1, float(confidence)))
        return faces


# ========== 绘制函数 ==========

def draw_results(frame, results, show_label=True):
    """在帧上绘制检测结果"""
    for i, face in enumerate(results):
        x, y, w, h = face["bbox"]
        conf = face["confidence"]

        # 人脸框
        cv.rectangle(frame, (x, y), (x + w, y + h), C_FACE, 2)

        # 标签
        if show_label:
            label = f"#{i+1} {conf:.0%}"
            (tw, th), _ = cv.getTextSize(label, cv.FONT_HERSHEY_SIMPLEX, 0.5, 1)
            cv.rectangle(frame, (x, y - th - 8), (x + tw + 6, y), C_FACE, -1)
            cv.putText(frame, label, (x + 3, y - 5),
                       cv.FONT_HERSHEY_SIMPLEX, 0.5, C_TEXT, 1)

    return frame


def mosaic_faces(frame, results, level=20):
    """对人脸区域打马赛克"""
    for face in results:
        x, y, w, h = face["bbox"]
        roi = frame[y:y + h, x:x + w]
        if roi.size == 0:
            continue
        small = cv.resize(roi, (max(w // level, 1), max(h // level, 1)))
        mosaic = cv.resize(small, (w, h), interpolation=cv.INTER_NEAREST)
        frame[y:y + h, x:x + w] = mosaic
    return frame


def blur_faces(frame, results, strength=51):
    """对人脸区域高斯模糊"""
    for face in results:
        x, y, w, h = face["bbox"]
        roi = frame[y:y + h, x:x + w]
        if roi.size == 0:
            continue
        blurred = cv.GaussianBlur(roi, (strength, strength), 0)
        frame[y:y + h, x:x + w] = blurred
    return frame


def crop_faces(frame, results, output_dir="cropped_faces"):
    """裁剪并保存每个人脸"""
    os.makedirs(output_dir, exist_ok=True)
    saved = []
    for i, face in enumerate(results):
        x, y, w, h = face["bbox"]
        pad = int(max(w, h) * 0.1)
        x1, y1 = max(0, x - pad), max(0, y - pad)
        x2, y2 = min(frame.shape[1], x + w + pad), min(frame.shape[0], y + h + pad)
        crop = frame[y1:y2, x1:x2]
        if crop.size == 0:
            continue
        path = os.path.join(output_dir, f"face_{i+1}.jpg")
        cv.imwrite(path, crop)
        saved.append(path)
    return saved


# ========== 处理模式 ==========

def process_image(detector, input_path, output_path=None,
                  mosaic=False, blur=False, crop=False, export_json=False):
    """处理单张图片"""
    # 支持URL
    if input_path.startswith("http"):
        print(f"[下载] {input_path}")
        tmp = f"_tmp_{int(time.time())}.jpg"
        if not download_file(input_path, tmp):
            return
        input_path = tmp

    if not os.path.exists(input_path):
        print(f"[错误] 找不到图片: {input_path}")
        return

    img = cv.imread(input_path)
    if img is None:
        print(f"[错误] 无法读取图片: {input_path}")
        return

    print(f"[信息] 图片尺寸: {img.shape[1]}x{img.shape[0]}")
    if _HEADLESS:
        print("[信息] 无头模式，跳过GUI显示")

    t0 = time.time()
    result, faces = detector.detect(img)
    dt = time.time() - t0

    # 绘制结果
    result = draw_results(result, faces)

    # 隐私处理
    if mosaic:
        result = mosaic_faces(result, faces)
        print("[隐私] 已对人脸区域打马赛克")
    if blur:
        result = blur_faces(result, faces)
        print("[隐私] 已对人脸区域模糊处理")

    # 裁剪人脸
    if crop and faces:
        saved = crop_faces(result, faces)
        print(f"[裁剪] 已保存 {len(saved)} 张人脸到 cropped_faces/")

    print(f"[结果] 检测到 {len(faces)} 张人脸，耗时 {dt*1000:.0f}ms")

    # 信息栏
    result = draw_info_bar(result, f"Faces: {len(faces)}  Time: {dt*1000:.0f}ms")

    # 保存
    save_path = output_path or "result_effects.jpg"
    cv.imwrite(save_path, result)
    print(f"[保存] {save_path}")

    # JSON导出
    if export_json and faces:
        json_path = save_path.rsplit(".", 1)[0] + ".json"
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump({"timestamp": datetime.now().isoformat(), "faces": faces}, f, indent=2, ensure_ascii=False)
        print(f"[导出] {json_path}")

    # 显示
    display = resize_for_display(result)
    safe_show("Face Detection", display)
    safe_wait_key(0)
    safe_destroy()


def process_camera(detector, camera_id=0, mosaic=False, blur=False):
    """摄像头实时检测"""
    cap = cv.VideoCapture(camera_id)
    if not cap.isOpened():
        print("[错误] 无法打开摄像头")
        return

    print("[提示] 按 'q' 退出 | 's' 截图 | 'm' 切换马赛克 | 'b' 切换模糊")
    mosaic_on = mosaic
    blur_on = blur
    ss_count = 0

    while True:
        ret, frame = cap.read()
        if not ret:
            break

        result, faces = detector.detect(frame)
        result = draw_results(result, faces)

        if mosaic_on:
            result = mosaic_faces(result, faces)
        if blur_on:
            result = blur_faces(result, faces)

        fps = detector._smooth_fps()
        result = draw_info_bar(result, f"Faces: {len(faces)}  FPS: {fps:.1f}  {'[MOSAIC]' if mosaic_on else ''} {'[BLUR]' if blur_on else ''}")

        display = resize_for_display(result)
        safe_show("Face Detection (Camera)", display)

        key = safe_wait_key(1)
        if key == ord('q'):
            break
        elif key == ord('s'):
            ss_count += 1
            path = f"screenshot_{ss_count}.jpg"
            cv.imwrite(path, result)
            print(f"[截图] {path}")
        elif key == ord('m'):
            mosaic_on = not mosaic_on
            print(f"[切换] 马赛克: {'开' if mosaic_on else '关'}")
        elif key == ord('b'):
            blur_on = not blur_on
            print(f"[切换] 模糊: {'开' if blur_on else '关'}")

    cap.release()
    safe_destroy()


def process_video(detector, video_path, output_path=None, mosaic=False, blur=False):
    """处理视频文件"""
    cap = cv.VideoCapture(video_path)
    if not cap.isOpened():
        print(f"[错误] 无法打开视频: {video_path}")
        return

    fps = cap.get(cv.CAP_PROP_FPS)
    w = int(cap.get(cv.CAP_PROP_FRAME_WIDTH))
    h = int(cap.get(cv.CAP_PROP_FRAME_HEIGHT))
    total = int(cap.get(cv.CAP_PROP_FRAME_COUNT))

    print(f"[信息] {w}x{h} @ {fps:.1f}fps, 共{total}帧")

    writer = None
    if output_path:
        fourcc = cv.VideoWriter_fourcc(*'mp4v')
        writer = cv.VideoWriter(output_path, fourcc, fps, (w, h))

    idx = 0
    t_start = time.time()

    while True:
        ret, frame = cap.read()
        if not ret:
            break

        idx += 1
        result, faces = detector.detect(frame)
        result = draw_results(result, faces)

        if mosaic:
            result = mosaic_faces(result, faces)
        if blur:
            result = blur_faces(result, faces)

        # 信息栏 + 进度条
        elapsed = time.time() - t_start
        eta = (elapsed / idx) * (total - idx) if idx > 0 else 0
        info = f"Frame: {idx}/{total}  Faces: {len(faces)}  ETA: {eta:.0f}s"
        result = draw_info_bar(result, info)
        draw_progress_bar(result, idx, total)

        if writer:
            writer.write(result)

        display = resize_for_display(result)
        safe_show("Face Detection (Video)", display)

        key = safe_wait_key(1)
        if key == ord('q'):
            print(f"[中断] 已处理 {idx}/{total} 帧")
            break

        if idx % 50 == 0:
            pct = idx / total * 100
            print(f"[进度] {idx}/{total} ({pct:.0f}%) ETA: {eta:.0f}s")

    cap.release()
    if writer:
        writer.release()
        print(f"[保存] {output_path}")

    total_time = time.time() - t_start
    print(f"[完成] 处理 {idx} 帧，耗时 {total_time:.1f}s ({idx/total_time:.1f} fps)")
    safe_destroy()


# ========== 主函数 ==========

def main():
    usage = """
人脸检测工具（增强版 v2）

用法:
  python face_detector_enhanced.py [选项]

输入源:
  -i, --image <路径>     检测图片（支持本地路径或URL）
  -c, --camera           使用摄像头实时检测
  -v, --video <路径>     检测视频文件
  -o, --output <路径>    保存结果

检测特征:
  --nose                 检测鼻子（默认开启）
  --no-nose              不检测鼻子
  --mouth                检测嘴巴（默认开启）
  --no-mouth             不检测嘴巴
  --eyes                 检测眼睛
  --smile                检测微笑
  --profile              检测侧脸

检测引擎:
  --dnn                  使用DNN深度学习模型（更准确）
  --haar                 使用Haar级联（默认，更快）

隐私保护:
  --mosaic               对人脸区域打马赛克
  --blur                 对人脸区域高斯模糊

输出选项:
  --crop                 裁剪并保存每个人脸
  --json                 导出检测结果为JSON

示例:
  python face_detector_enhanced.py -i people.jpg
  python face_detector_enhanced.py -i people.jpg -o result.jpg --eyes --smile
  python face_detector_enhanced.py -i people.jpg --mosaic --json
  python face_detector_enhanced.py -i https://example.com/photo.jpg
  python face_detector_enhanced.py -c --dnn
  python face_detector_enhanced.py -v video.mp4 -o output.mp4 --blur
"""

    # 默认参数
    input_path = "people.jpg"
    mode = "image"
    output_path = None
    detect_nose = True
    detect_eyes = False
    detect_smile = False
    detect_mouth = True
    detect_profile = False
    use_dnn = False
    do_mosaic = False
    do_blur = False
    do_crop = False
    do_json = False

    # 解析参数
    args = sys.argv[1:]
    i = 0
    while i < len(args):
        a = args[i]
        if a in ('-h', '--help'):
            print(usage); return
        elif a in ('-i', '--image'):
            mode = "image"
            input_path = args[i + 1] if i + 1 < len(args) else "people.jpg"
            i += 1
        elif a in ('-c', '--camera'):
            mode = "camera"
        elif a in ('-v', '--video'):
            mode = "video"
            input_path = args[i + 1] if i + 1 < len(args) else ""
            i += 1
        elif a in ('-o', '--output'):
            output_path = args[i + 1] if i + 1 < len(args) else None
            i += 1
        elif a == '--nose': detect_nose = True
        elif a == '--no-nose': detect_nose = False
        elif a == '--mouth': detect_mouth = True
        elif a == '--no-mouth': detect_mouth = False
        elif a == '--eyes': detect_eyes = True
        elif a == '--smile': detect_smile = True
        elif a == '--profile': detect_profile = True
        elif a == '--dnn': use_dnn = True
        elif a == '--haar': use_dnn = False
        elif a == '--mosaic': do_mosaic = True
        elif a == '--blur': do_blur = True
        elif a == '--crop': do_crop = True
        elif a == '--json': do_json = True
        i += 1

    # 启动
    print("=" * 45)
    print("  人脸检测工具（增强版 v2）")
    print(f"  引擎: {'DNN (CNN)' if use_dnn else 'Haar Cascade'}")
    features = ["人脸"]
    if detect_eyes: features.append("眼睛")
    if detect_nose: features.append("鼻子")
    if detect_mouth: features.append("嘴巴")
    if detect_smile: features.append("微笑")
    if detect_profile: features.append("侧脸")
    print(f"  特征: {' + '.join(features)}")
    if _HEADLESS:
        print("  模式: 无头（无GUI显示）")
    print("=" * 45)

    detector = FaceDetector(
        use_dnn=use_dnn,
        detect_nose=detect_nose,
        detect_eyes=detect_eyes,
        detect_smile=detect_smile,
        detect_mouth=detect_mouth,
        detect_profile=detect_profile,
    )

    if mode == "camera":
        process_camera(detector, mosaic=do_mosaic, blur=do_blur)
    elif mode == "video":
        if not input_path:
            print("[错误] 请指定视频路径: -v <路径>")
            return
        process_video(detector, input_path, output_path, mosaic=do_mosaic, blur=do_blur)
    else:
        process_image(detector, input_path, output_path,
                      mosaic=do_mosaic, blur=do_blur, crop=do_crop, export_json=do_json)


if __name__ == "__main__":
    main()
