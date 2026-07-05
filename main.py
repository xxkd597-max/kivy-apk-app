import os
import sys
import math
import time

from kivy.app import App
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.image import Image as KivyImage
from kivy.uix.label import Label
from kivy.uix.scrollview import ScrollView
from kivy.uix.popup import Popup
from kivy.uix.filechooser import FileChooserListView
from kivy.core.window import Window
from kivy.core.image import Image as CoreImage
from kivy.graphics import Color, Rectangle
from kivy.clock import Clock


# ------------------- 中文字体设置 -------------------
def register_chinese_font():
    """
    安卓端优先读取打包进 APK 的 NotoSansSC-Regular.ttf。
    如果没有字体文件，部分手机可能中文显示为方块。
    """
    try:
        from kivy.core.text import LabelBase
    except Exception:
        return None

    font_file = "NotoSansSC-Regular.ttf"

    if os.path.exists(font_file):
        try:
            LabelBase.register(name="ChineseFont", fn_regular=font_file)
            return "ChineseFont"
        except Exception:
            pass

    if sys.platform.startswith("win"):
        font_candidates = [
            "C:/Windows/Fonts/msyh.ttc",
            "C:/Windows/Fonts/simsun.ttc",
            "C:/Windows/Fonts/simhei.ttf",
        ]
        for path in font_candidates:
            if os.path.exists(path):
                try:
                    LabelBase.register(name="ChineseFont", fn_regular=path)
                    return "ChineseFont"
                except Exception:
                    continue

    return None


FONT_NAME = register_chinese_font()


def font_kwargs():
    if FONT_NAME:
        return {"font_name": FONT_NAME}
    return {}


# ------------------- 带背景布局 -------------------
class StyledBoxLayout(BoxLayout):
    def __init__(self, bg_color=(0.96, 0.96, 0.98, 1), **kwargs):
        super().__init__(**kwargs)
        with self.canvas.before:
            Color(*bg_color)
            self.rect = Rectangle(size=self.size, pos=self.pos)
        self.bind(size=self._update_rect, pos=self._update_rect)

    def _update_rect(self, instance, value):
        self.rect.pos = instance.pos
        self.rect.size = instance.size


# ------------------- 纯 Kivy 图像分析模块，不依赖 OpenCV / NumPy -------------------
class ImageQualityAnalyzer:
    @staticmethod
    def load_texture(filepath):
        """
        使用 Kivy CoreImage 加载图片。
        支持 jpg、jpeg、png、bmp、webp 等常见格式，具体取决于 Kivy/SDL2_image 支持情况。
        """
        if not os.path.exists(filepath):
            raise ValueError("文件不存在")

        try:
            core_img = CoreImage(filepath)
            texture = core_img.texture
            if texture is None:
                raise ValueError("图片纹理加载失败")
            return texture, texture.width, texture.height
        except Exception as e:
            raise ValueError("无法加载图片：" + str(e))

    @staticmethod
    def texture_to_gray_grid(texture, max_side=420):
        """
        将纹理转为灰度网格。
        为避免手机内存过高，会自动抽样缩小。
        """
        w, h = texture.width, texture.height
        pixels = texture.pixels
        colorfmt = texture.colorfmt.lower()

        if colorfmt in ("rgba", "bgra"):
            channels = 4
        elif colorfmt in ("rgb", "bgr"):
            channels = 3
        elif colorfmt in ("luminance", "alpha"):
            channels = 1
        else:
            # 大多数情况下 Kivy 是 rgba；未知格式按 rgba 尝试
            channels = 4

        if w <= 0 or h <= 0:
            raise ValueError("图片尺寸异常")

        step = max(1, int(math.ceil(max(w, h) / float(max_side))))

        gray_grid = []
        flat_gray = []

        for y in range(0, h, step):
            row = []
            for x in range(0, w, step):
                idx = (y * w + x) * channels

                if idx >= len(pixels):
                    continue

                if channels == 1:
                    gray = pixels[idx]
                else:
                    if colorfmt == "bgra":
                        b = pixels[idx]
                        g = pixels[idx + 1]
                        r = pixels[idx + 2]
                    elif colorfmt == "bgr":
                        b = pixels[idx]
                        g = pixels[idx + 1]
                        r = pixels[idx + 2]
                    else:
                        r = pixels[idx]
                        g = pixels[idx + 1]
                        b = pixels[idx + 2]

                    gray = int(0.299 * r + 0.587 * g + 0.114 * b)

                row.append(gray)
                flat_gray.append(gray)

            if row:
                gray_grid.append(row)

        if not gray_grid or not flat_gray:
            raise ValueError("图片像素读取失败")

        return gray_grid, flat_gray, len(gray_grid[0]), len(gray_grid)

    @staticmethod
    def sharpness_laplacian(gray_grid):
        """
        拉普拉斯近似清晰度。
        OpenCV 版本是 cv2.Laplacian，这里用纯 Python 近似实现。
        """
        h = len(gray_grid)
        w = len(gray_grid[0])

        if h < 3 or w < 3:
            return 0.0

        values = []

        for y in range(1, h - 1):
            for x in range(1, w - 1):
                c = gray_grid[y][x]
                lap = (
                    gray_grid[y - 1][x]
                    + gray_grid[y + 1][x]
                    + gray_grid[y][x - 1]
                    + gray_grid[y][x + 1]
                    - 4 * c
                )
                values.append(lap)

        if not values:
            return 0.0

        mean_v = sum(values) / len(values)
        var_v = sum((v - mean_v) ** 2 for v in values) / len(values)
        return var_v

    @staticmethod
    def exposure_analysis(flat_gray):
        total = len(flat_gray)
        if total == 0:
            return 0.0, 0.0, 0.0, 0.0

        over_count = sum(1 for v in flat_gray if v >= 241)
        under_count = sum(1 for v in flat_gray if v <= 15)

        over_ratio = over_count / total
        under_ratio = under_count / total
        mean_brightness = sum(flat_gray) / total

        base = 1.0 - (over_ratio + under_ratio)
        bonus = 0.1 if 70 < mean_brightness < 180 else 0.0
        score = max(0.0, min(1.0, base + bonus))

        return score, over_ratio, under_ratio, mean_brightness

    @staticmethod
    def noise_estimation(gray_grid):
        """
        简化噪点评估：用中心像素与周围像素均值的残差估计噪点。
        """
        h = len(gray_grid)
        w = len(gray_grid[0])

        if h < 3 or w < 3:
            return 0.8, 0.0

        residuals = []

        for y in range(1, h - 1):
            for x in range(1, w - 1):
                c = gray_grid[y][x]
                nb = (
                    gray_grid[y - 1][x]
                    + gray_grid[y + 1][x]
                    + gray_grid[y][x - 1]
                    + gray_grid[y][x + 1]
                ) / 4.0
                residuals.append(abs(c - nb))

        if not residuals:
            return 0.8, 0.0

        avg_residual = sum(residuals) / len(residuals)
        noise_level = avg_residual / 255.0

        score = max(0.1, min(1.0, 1.0 - noise_level * 2.2))
        return score, noise_level

    @staticmethod
    def overall_score(sharp_score, exp_score, noise_score):
        raw = 100 * (0.4 * sharp_score + 0.3 * exp_score + 0.3 * noise_score)
        return int(round(max(0, min(100, raw))))

    @staticmethod
    def evaluate(texture):
        gray_grid, flat_gray, sw, sh = ImageQualityAnalyzer.texture_to_gray_grid(texture)

        sharp_raw = ImageQualityAnalyzer.sharpness_laplacian(gray_grid)
        sharp_norm = min(1.0, sharp_raw / 900.0)

        exp_norm, over_r, under_r, mean_b = ImageQualityAnalyzer.exposure_analysis(flat_gray)
        noise_norm, noise_var = ImageQualityAnalyzer.noise_estimation(gray_grid)

        # 噪点会影响清晰度判断，加入轻微惩罚
        sharp_norm = sharp_norm * (0.7 + 0.3 * noise_norm)
        sharp_norm = max(0.0, min(1.0, sharp_norm))

        total = ImageQualityAnalyzer.overall_score(sharp_norm, exp_norm, noise_norm)

        if sharp_norm < 0.3:
            sharp_desc = "严重模糊"
        elif sharp_norm < 0.6:
            sharp_desc = "轻度模糊"
        elif sharp_norm < 0.8:
            sharp_desc = "清晰度良好"
        else:
            sharp_desc = "非常清晰"

        if over_r > 0.1:
            exp_desc = "过曝"
        elif under_r > 0.1:
            exp_desc = "欠曝"
        else:
            exp_desc = "曝光正常"

        if noise_norm < 0.35:
            noise_desc = "噪点较多"
        elif noise_norm < 0.7:
            noise_desc = "轻微噪点"
        else:
            noise_desc = "噪点较少"

        return {
            "total": total,
            "sample_size": f"{sw} × {sh}",
            "sharpness_raw": round(sharp_raw, 2),
            "sharpness_norm": round(sharp_norm, 2),
            "exposure_norm": round(exp_norm, 2),
            "noise_norm": round(noise_norm, 2),
            "overexposed_ratio": round(over_r, 3),
            "underexposed_ratio": round(under_r, 3),
            "mean_brightness": round(mean_b, 1),
            "noise_variance": round(noise_var, 4),
            "desc": f"{sharp_desc}，{exp_desc}，{noise_desc}",
        }


# ------------------- 主界面 -------------------
class ImageQualityApp(App):
    def build(self):
        self.title = "图像画质分析工具"

        Window.background_color = (0.94, 0.94, 0.96, 1)

        root = StyledBoxLayout(
            orientation="vertical",
            padding=16,
            spacing=12,
            bg_color=(0.94, 0.94, 0.96, 1),
        )

        title_label = Label(
            text="图像画质分析工具",
            font_size=22,
            size_hint=(1, 0.08),
            color=(0.15, 0.25, 0.45, 1),
            bold=True,
            **font_kwargs()
        )
        root.add_widget(title_label)

        btn_layout = BoxLayout(size_hint=(1, 0.08), spacing=12)

        self.btn_select = Button(
            text="选择图片",
            font_size=16,
            background_color=(0.25, 0.55, 0.85, 1),
            background_normal="",
            color=(1, 1, 1, 1),
            **font_kwargs()
        )
        self.btn_select.bind(on_press=self.open_filechooser)

        self.btn_analyze = Button(
            text="开始分析",
            font_size=16,
            background_color=(0.3, 0.7, 0.45, 1),
            background_normal="",
            color=(1, 1, 1, 1),
            disabled=True,
            **font_kwargs()
        )
        self.btn_analyze.bind(on_press=self.analyze_image)

        btn_layout.add_widget(self.btn_select)
        btn_layout.add_widget(self.btn_analyze)
        root.add_widget(btn_layout)

        preview_card = StyledBoxLayout(
            orientation="vertical",
            size_hint=(1, 0.45),
            padding=10,
            bg_color=(1, 1, 1, 1),
        )

        preview_label = Label(
            text="图片预览",
            font_size=14,
            size_hint=(1, 0.12),
            color=(0.3, 0.3, 0.3, 1),
            halign="left",
            valign="middle",
            **font_kwargs()
        )
        preview_label.bind(size=preview_label.setter("text_size"))
        preview_card.add_widget(preview_label)

        self.image_widget = KivyImage(size_hint=(1, 0.88), fit_mode="contain")
        preview_card.add_widget(self.image_widget)
        root.add_widget(preview_card)

        result_card = StyledBoxLayout(
            orientation="vertical",
            size_hint=(1, 0.39),
            padding=12,
            bg_color=(1, 1, 1, 1),
        )

        result_title = Label(
            text="分析结果",
            font_size=14,
            size_hint=(1, 0.12),
            color=(0.3, 0.3, 0.3, 1),
            halign="left",
            valign="middle",
            **font_kwargs()
        )
        result_title.bind(size=result_title.setter("text_size"))
        result_card.add_widget(result_title)

        scroll = ScrollView(size_hint=(1, 0.88))

        self.result_label = Label(
            text="请选择图片后点击「开始分析」按钮",
            font_size=13,
            size_hint_y=None,
            halign="left",
            valign="top",
            color=(0.2, 0.2, 0.2, 1),
            line_height=1.5,
            **font_kwargs()
        )
        self.result_label.bind(width=self._update_result_text_width)
        self.result_label.bind(texture_size=self._update_result_height)

        scroll.add_widget(self.result_label)
        result_card.add_widget(scroll)
        root.add_widget(result_card)

        self.current_image_path = None
        self.current_texture = None
        self.full_size = None

        return root

    def _update_result_text_width(self, instance, width):
        instance.text_size = (width, None)

    def _update_result_height(self, instance, texture_size):
        instance.height = texture_size[1] + 20

    def show_popup(self, title, message):
        content = BoxLayout(orientation="vertical", padding=15, spacing=10)

        label = Label(
            text=message,
            font_size=14,
            halign="left",
            valign="middle",
            **font_kwargs()
        )
        label.bind(size=label.setter("text_size"))
        content.add_widget(label)

        btn = Button(
            text="确定",
            size_hint=(1, 0.25),
            font_size=15,
            **font_kwargs()
        )
        content.add_widget(btn)

        popup = Popup(
            title=title,
            content=content,
            size_hint=(0.85, 0.45),
        )

        btn.bind(on_press=popup.dismiss)
        popup.open()

    def get_default_image_path(self):
        candidates = [
            "/storage/emulated/0/DCIM",
            "/storage/emulated/0/Pictures",
            "/storage/emulated/0/Download",
            "/sdcard/DCIM",
            "/sdcard/Pictures",
            "/sdcard/Download",
            os.getcwd(),
        ]

        for path in candidates:
            if os.path.exists(path):
                return path

        return os.getcwd()

    def open_filechooser(self, instance):
        layout = BoxLayout(orientation="vertical", spacing=8, padding=8)

        chooser = FileChooserListView(
            path=self.get_default_image_path(),
            filters=["*.jpg", "*.jpeg", "*.png", "*.bmp", "*.webp", "*.JPG", "*.JPEG", "*.PNG", "*.BMP"],
        )

        layout.add_widget(chooser)

        btn_box = BoxLayout(size_hint=(1, 0.12), spacing=8)

        btn_cancel = Button(
            text="取消",
            font_size=14,
            **font_kwargs()
        )

        btn_ok = Button(
            text="选择当前图片",
            font_size=14,
            background_color=(0.25, 0.55, 0.85, 1),
            background_normal="",
            color=(1, 1, 1, 1),
            **font_kwargs()
        )

        btn_box.add_widget(btn_cancel)
        btn_box.add_widget(btn_ok)
        layout.add_widget(btn_box)

        popup = Popup(
            title="选择图片",
            content=layout,
            size_hint=(0.95, 0.9),
        )

        btn_cancel.bind(on_press=popup.dismiss)

        def confirm_select(*args):
            self.load_selected(chooser.selection, popup)

        btn_ok.bind(on_press=confirm_select)

        chooser.bind(on_submit=lambda chooser_instance, selection, touch: self.load_selected(selection, popup))

        popup.open()

    def load_selected(self, selection, popup):
        popup.dismiss()

        if not selection:
            self.show_popup("提示", "请先选择一张图片")
            return

        filepath = selection[0]

        try:
            texture, w, h = ImageQualityAnalyzer.load_texture(filepath)

            self.current_image_path = filepath
            self.current_texture = texture
            self.full_size = (w, h)

            self.image_widget.source = filepath
            self.image_widget.reload()

            self.btn_analyze.disabled = False

            self.result_label.text = (
                f"已加载图片：{os.path.basename(filepath)}\n"
                f"图片尺寸：{w} × {h} 像素\n\n"
                f"点击「开始分析」查看画质评分"
            )

        except Exception as e:
            self.current_image_path = None
            self.current_texture = None
            self.btn_analyze.disabled = True
            self.result_label.text = "加载失败：" + str(e)

    def analyze_image(self, instance):
        if self.current_texture is None:
            self.show_popup("提示", "请先选择图片")
            return

        self.result_label.text = "正在分析中，请稍候..."
        Clock.schedule_once(self._run_analysis, 0.1)

    def _run_analysis(self, dt):
        try:
            start = time.time()
            result = ImageQualityAnalyzer.evaluate(self.current_texture)
            elapsed = (time.time() - start) * 1000.0

            text = f"综合画质评分：{result['total']} 分（满分 100）\n"
            text += f"整体评价：{result['desc']}\n"
            text += f"分析耗时：{elapsed:.0f} 毫秒\n"
            text += f"分析采样尺寸：{result['sample_size']}\n"
            text += "----------------------------------------\n"
            text += "【清晰度】 拉普拉斯近似算法\n"
            text += f"    原始值：{result['sharpness_raw']:.3f}\n"
            text += f"    归一化得分：{result['sharpness_norm']:.3f}\n\n"
            text += "【曝光评估】 灰度直方图统计法\n"
            text += f"    归一化得分：{result['exposure_norm']:.3f}\n"
            text += f"    过曝像素占比：{result['overexposed_ratio']:.1%}\n"
            text += f"    欠曝像素占比：{result['underexposed_ratio']:.1%}\n"
            text += f"    平均亮度：{result['mean_brightness']:.1f}\n\n"
            text += "【噪点评估】 邻域残差估计法\n"
            text += f"    归一化得分：{result['noise_norm']:.3f}\n"
            text += f"    噪声强度估计：{result['noise_variance']:.3f}\n\n"
            text += "说明：当前 APK 版本不依赖 OpenCV / NumPy，因此算法为移动端轻量近似版。"

            self.result_label.text = text

        except Exception as e:
            self.result_label.text = "分析出错：" + str(e)


if __name__ == "__main__":
    ImageQualityApp().run()
