"""
人脸检测（优化版）
- 合并人脸+鼻子检测为一个脚本
- 添加异常处理、参数配置、命令行支持
- 支持图片/摄像头/视频输入
- 自动缩放显示、FPS显示
"""

import cv2 as cv
import sys
import os
import time

# ========== 配置 ==========
CASCADE_DIR = "cascade_files"
FACE_CASCADE = os.path.join(CASCADE_DIR, "haarcascade_frontalface_alt.xml")
NOSE_CASCADE = os.path.join(CASCADE_DIR, "haarcascade_mcs_nose.xml")
EYE_CASCADE = os.path.join(CASCADE_DIR, "haarcascade_eye.xml")
SMILE_CASCADE = os.path.join(CASCADE_DIR, "haarcascade_smile.xml")

# 检测参数
SCALE_FACTOR = 1.3
MIN_NEIGHBORS = 5
MIN_FACE_SIZE = (30, 30)

# 显示参数
MAX_DISPLAY_WIDTH = 800
MAX_DISPLAY_HEIGHT = 600

# 颜色 (BGR)
COLOR_FACE = (0, 0, 255)      # 红色 - 人脸框
COLOR_NOSE = (0, 255, 0)      # 绿色 - 鼻子
COLOR_EYE = (255, 0, 0)       # 蓝色 - 眼睛
COLOR_SMILE = (0, 255, 255)   # 黄色 - 微笑
COLOR_TEXT = (255, 255, 255)   # 白色 - 文字


class FaceDetector:
    """人脸检测器"""

    def __init__(self, detect_nose=True, detect_eyes=False, detect_smile=False):
        self.detect_nose = detect_nose
        self.detect_eyes = detect_eyes
        self.detect_smile = detect_smile

        # 加载级联分类器
        self.face_cascade = self._load_cascade(FACE_CASCADE, "人脸")
        self.nose_cascade = self._load_cascade(NOSE_CASCADE, "鼻子") if detect_nose else None
        self.eye_cascade = self._load_cascade(EYE_CASCADE, "眼睛") if detect_eyes else None
        self.smile_cascade = self._load_cascade(SMILE_CASCADE, "微笑") if detect_smile else None

    @staticmethod
    def _load_cascade(path, name):
        """加载级联分类器，失败时退出"""
        if not os.path.exists(path):
            print(f"[错误] 找不到{name}分类器文件: {path}")
            sys.exit(1)
        cascade = cv.CascadeClassifier(path)
        if cascade.empty():
            print(f"[错误] {name}分类器加载失败: {path}")
            sys.exit(1)
        print(f"[OK] {name}分类器已加载")
        return cascade

    def detect(self, frame):
        """检测人脸及特征，返回标注后的帧和统计信息"""
        gray = cv.cvtColor(frame, cv.COLOR_BGR2GRAY)
        # 直方图均衡化，提高检测率
        gray = cv.equalizeHist(gray)

        faces = self.face_cascade.detectMultiScale(
            gray, SCALE_FACTOR, MIN_NEIGHBORS, minSize=MIN_FACE_SIZE
        )

        face_count = 0
        for (x, y, w, h) in faces:
            face_count += 1
            # 人脸框
            cv.rectangle(frame, (x, y), (x + w, y + h), COLOR_FACE, 2)
            cv.putText(frame, f"Face #{face_count}", (x, y - 8),
                       cv.FONT_HERSHEY_SIMPLEX, 0.5, COLOR_FACE, 1)

            roi_gray = gray[y:y + h, x:x + w]
            roi_color = frame[y:y + h, x:x + w]

            # 鼻子检测（每个人脸只取第一个）
            if self.nose_cascade:
                noses = self.nose_cascade.detectMultiScale(roi_gray, SCALE_FACTOR, MIN_NEIGHBORS)
                for (nx, ny, nw, nh) in noses[:1]:
                    cv.rectangle(roi_color, (nx, ny), (nx + nw, ny + nh), COLOR_NOSE, 2)

            # 眼睛检测
            if self.eye_cascade:
                eyes = self.eye_cascade.detectMultiScale(roi_gray, SCALE_FACTOR, MIN_NEIGHBORS)
                for (ex, ey, ew, eh) in eyes:
                    cv.rectangle(roi_color, (ex, ey), (ex + ew, ey + eh), COLOR_EYE, 2)

            # 微笑检测
            if self.smile_cascade:
                smiles = self.smile_cascade.detectMultiScale(
                    roi_gray, SCALE_FACTOR, 20, minSize=(25, 25)
                )
                if len(smiles) > 0:
                    cv.putText(frame, "Smile!", (x, y + h + 20),
                               cv.FONT_HERSHEY_SIMPLEX, 0.6, COLOR_SMILE, 2)

        return frame, face_count


def resize_for_display(frame):
    """缩放图片以适应显示窗口"""
    h, w = frame.shape[:2]
    if w > MAX_DISPLAY_WIDTH or h > MAX_DISPLAY_HEIGHT:
        scale = min(MAX_DISPLAY_WIDTH / w, MAX_DISPLAY_HEIGHT / h)
        frame = cv.resize(frame, (int(w * scale), int(h * scale)))
    return frame


def process_image(detector, input_path, output_path=None):
    """处理单张图片"""
    if not os.path.exists(input_path):
        print(f"[错误] 找不到图片: {input_path}")
        return

    img = cv.imread(input_path)
    if img is None:
        print(f"[错误] 无法读取图片: {input_path}")
        return

    result, count = detector.detect(img)
    print(f"[结果] 检测到 {count} 张人脸")

    if output_path:
        cv.imwrite(output_path, result)
        print(f"[保存] {output_path}")

    display = resize_for_display(result)
    cv.imshow("Face Detection", display)
    cv.waitKey(0)
    cv.destroyAllWindows()


def process_camera(detector, camera_id=0):
    """处理摄像头实时画面"""
    cap = cv.VideoCapture(camera_id)
    if not cap.isOpened():
        print("[错误] 无法打开摄像头")
        return

    print("[提示] 按 'q' 退出, 's' 截图保存")
    screenshot_count = 0

    while True:
        ret, frame = cap.read()
        if not ret:
            break

        start = time.time()
        result, count = detector.detect(frame)
        fps = 1.0 / (time.time() - start + 1e-6)

        # 显示FPS和人脸数
        cv.putText(result, f"Faces: {count}  FPS: {fps:.1f}", (10, 30),
                   cv.FONT_HERSHEY_SIMPLEX, 0.7, COLOR_TEXT, 2)

        display = resize_for_display(result)
        cv.imshow("Face Detection (Camera)", display)

        key = cv.waitKey(1) & 0xFF
        if key == ord('q'):
            break
        elif key == ord('s'):
            screenshot_count += 1
            path = f"screenshot_{screenshot_count}.jpg"
            cv.imwrite(path, result)
            print(f"[截图] {path}")

    cap.release()
    cv.destroyAllWindows()


def process_video(detector, video_path, output_path=None):
    """处理视频文件"""
    cap = cv.VideoCapture(video_path)
    if not cap.isOpened():
        print(f"[错误] 无法打开视频: {video_path}")
        return

    fps = cap.get(cv.CAP_PROP_FPS)
    width = int(cap.get(cv.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv.CAP_PROP_FRAME_HEIGHT))
    total = int(cap.get(cv.CAP_PROP_FRAME_COUNT))

    print(f"[信息] 视频: {width}x{height} @ {fps:.1f}fps, 共{total}帧")

    writer = None
    if output_path:
        fourcc = cv.VideoWriter_fourcc(*'mp4v')
        writer = cv.VideoWriter(output_path, fourcc, fps, (width, height))

    frame_idx = 0
    while True:
        ret, frame = cap.read()
        if not ret:
            break

        frame_idx += 1
        result, count = detector.detect(frame)

        # 进度显示
        cv.putText(result, f"Frame: {frame_idx}/{total}  Faces: {count}", (10, 30),
                   cv.FONT_HERSHEY_SIMPLEX, 0.6, COLOR_TEXT, 2)

        if writer:
            writer.write(result)

        display = resize_for_display(result)
        cv.imshow("Face Detection (Video)", display)

        if cv.waitKey(1) & 0xFF == ord('q'):
            print(f"[提示] 用户中断，已处理 {frame_idx}/{total} 帧")
            break

        if frame_idx % 100 == 0:
            print(f"[进度] {frame_idx}/{total} ({frame_idx/total*100:.0f}%)")

    cap.release()
    if writer:
        writer.release()
        print(f"[保存] {output_path}")
    cv.destroyAllWindows()


def main():
    usage = """
人脸检测工具（优化版）

用法:
  python face_detector_optimized.py [选项]

选项:
  -i, --image <路径>     检测图片（默认: people.jpg）
  -c, --camera           使用摄像头实时检测
  -v, --video <路径>     检测视频文件
  -o, --output <路径>    保存结果（图片或视频）
  --nose                 检测鼻子（默认开启）
  --no-nose              不检测鼻子
  --eyes                 检测眼睛
  --smile                检测微笑
  -h, --help             显示帮助

示例:
  python face_detector_optimized.py -i people.jpg
  python face_detector_optimized.py -i people.jpg -o result.jpg
  python face_detector_optimized.py -c
  python face_detector_optimized.py -v video.mp4 -o output.mp4
  python face_detector_optimized.py -i people.jpg --eyes --smile
"""

    # 默认参数
    input_path = "people.jpg"
    mode = "image"  # image / camera / video
    output_path = None
    detect_nose = True
    detect_eyes = False
    detect_smile = False

    # 解析命令行参数
    args = sys.argv[1:]
    i = 0
    while i < len(args):
        arg = args[i]
        if arg in ('-h', '--help'):
            print(usage)
            return
        elif arg in ('-i', '--image'):
            mode = "image"
            input_path = args[i + 1] if i + 1 < len(args) else "people.jpg"
            i += 1
        elif arg in ('-c', '--camera'):
            mode = "camera"
        elif arg in ('-v', '--video'):
            mode = "video"
            input_path = args[i + 1] if i + 1 < len(args) else ""
            i += 1
        elif arg in ('-o', '--output'):
            output_path = args[i + 1] if i + 1 < len(args) else None
            i += 1
        elif arg == '--nose':
            detect_nose = True
        elif arg == '--no-nose':
            detect_nose = False
        elif arg == '--eyes':
            detect_eyes = True
        elif arg == '--smile':
            detect_smile = True
        i += 1

    # 初始化检测器
    print("=" * 40)
    print("  人脸检测工具（优化版）")
    print("=" * 40)
    detector = FaceDetector(
        detect_nose=detect_nose,
        detect_eyes=detect_eyes,
        detect_smile=detect_smile
    )

    # 执行检测
    if mode == "camera":
        process_camera(detector)
    elif mode == "video":
        if not input_path:
            print("[错误] 请指定视频文件路径: -v <路径>")
            return
        process_video(detector, input_path, output_path)
    else:
        process_image(detector, input_path, output_path)


if __name__ == "__main__":
    main()
