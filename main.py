import cv2
import numpy as np
from kivy.app import App
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.image import Image as KivyImage
from kivy.uix.label import Label
from kivy.uix.scrollview import ScrollView
from kivy.uix.popup import Popup
from kivy.uix.filechooser import FileChooserListView
from kivy.core.window import Window
from kivy.clock import Clock
from kivy.graphics import Color, Rectangle
import os
import sys

# ------------------- 跨平台中文字体设置 -------------------
def register_chinese_font():
    """跨平台字体加载：安卓端优先读打包自带字体，Windows端兜底系统字体"""
    from kivy.core.text import LabelBase

    # ========== 第1优先级：加载打包进APP的本地字体（安卓端生效） ==========    
    font_file = "NotoSansSC-Regular.ttf"
    if os.path.exists(font_file):
        try:
            LabelBase.register(name='ChineseFont', fn_regular=font_file)
            return 'ChineseFont'
        except:
            pass

    # ========== 第2优先级：Windows系统字体兜底（电脑调试用） ==========
    if sys.platform.startswith('win'):
        font_candidates = [
            'C:/Windows/Fonts/msyh.ttc',
            'C:/Windows/Fonts/simsun.ttc',
            'C:/Windows/Fonts/simhei.ttf',
        ]
        for path in font_candidates:
            if os.path.exists(path):
                try:
                    LabelBase.register(name='ChineseFont', fn_regular=path)
                    return 'ChineseFont'
                except:
                    continue
    return None

FONT_NAME = register_chinese_font()

# ------------------- 画质分析核心模块 -------------------
class ImageQualityAnalyzer:
    @staticmethod
    def load_image(filepath, max_size=1200):
        """安全读取图像，自动缩小大图防止OOM"""
        img = cv2.imdecode(np.fromfile(filepath, dtype=np.uint8), cv2.IMREAD_COLOR)
        if img is None:
            raise ValueError("无法解码图像，请检查文件格式和路径")
        h, w = img.shape[:2]
        if max(h, w) > max_size:
            scale = max_size / max(h, w)
            new_w, new_h = int(w * scale), int(h * scale)
            img_small = cv2.resize(img, (new_w, new_h), interpolation=cv2.INTER_AREA)
        else:
            img_small = img.copy()
        return img, img_small, (w, h)

    @staticmethod
    def sharpness_laplacian(img_gray):
           lap = cv2.Laplacian(img_gray, cv2.CV_64F)
           return lap.var()

    @staticmethod
    def exposure_analysis(img_gray):
        """曝光：直方图统计过曝/欠曝比例"""
        hist = cv2.calcHist([img_gray], [0], None, [256], [0, 256])
        total = img_gray.size
        overexposed_ratio = np.sum(hist[241:]) / total
        underexposed_ratio = np.sum(hist[:15]) / total
        base = 1.0 - (overexposed_ratio + underexposed_ratio)
        mean_brightness = np.mean(img_gray)
        bonus = 0.1 if 70 < mean_brightness < 180 else 0
        score = max(0.0, min(1.0, base + bonus))
        return score, overexposed_ratio, underexposed_ratio, mean_brightness

    @staticmethod
    def noise_estimation(img_gray):
        """噪点：中值滤波残差法"""
        denoised = cv2.medianBlur(img_gray, 3)
        diff = img_gray.astype(np.float32) - denoised.astype(np.float32)
        noise_var = np.var(diff) / 255.0
        score = max(0.1, 1.0 - noise_var * 1.2)
        return score, noise_var

    @staticmethod
    def overall_score(sharp_score, exp_score, noise_score):
        """综合评分 0-100，权重：清晰度0.4，曝光0.3，噪声0.3"""
        raw = 100 * (0.4 * sharp_score + 0.3 * exp_score + 0.3 * noise_score)
        return int(round(max(0, min(100, raw))))

    @staticmethod
    def evaluate(img_small):
        """综合分析，返回各维度结果"""
        gray = cv2.cvtColor(img_small, cv2.COLOR_BGR2GRAY) if len(img_small.shape) == 3 else img_small

        #1. 计算噪点
        noise_norm, noise_var = ImageQualityAnalyzer.noise_estimation(gray)

       #2. 计算清晰度，并加入噪点惩罚，避免高噪点图清晰度虚高
        sharp_raw = ImageQualityAnalyzer.sharpness_laplacian(gray)
        sharp_norm = min(1.0, sharp_raw / 700.0)
        #线性惩罚：噪点越多折扣越大，保留60%清晰度，避免矫枉过正
        sharp_norm = sharp_norm * (0.7+ 0.3 * noise_norm)
        sharp_norm = min(1.0, max(0.0, sharp_norm))

        #3. 计算曝光
        exp_norm, over_r, under_r, mean_b = ImageQualityAnalyzer.exposure_analysis(gray)

        #4. 计算综合分
        total = ImageQualityAnalyzer.overall_score(sharp_norm, exp_norm, noise_norm)

        # 文字描述
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
            noise_desc = "噪点极少"

        return {
            "total": total,
            "sharpness_raw": round(sharp_raw, 2),
            "sharpness_norm": round(sharp_norm, 2),
            "exposure_norm": round(exp_norm, 2),
            "noise_norm": round(noise_norm, 2),
            "overexposed_ratio": round(over_r, 3),
            "underexposed_ratio": round(under_r, 3),
            "mean_brightness": round(mean_b, 1),
            "noise_variance": round(noise_var, 4),
            "desc": f"{sharp_desc}，{exp_desc}，{noise_desc}"
        }

# ------------------- 带背景的布局组件 -------------------
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

# ------------------- Kivy UI 界面 -------------------
class ImageQualityApp(App):
    def build(self):
        self.title = "图像画质分析工具"
        Window.size = (900, 700)
        Window.background_color = (0.94, 0.94, 0.96, 1)

        root = StyledBoxLayout(orientation='vertical', padding=20, spacing=15, bg_color=(0.94, 0.94, 0.96, 1))

        # 标题
        title_label = Label(
            text="图像画质分析工具",
            font_name=FONT_NAME,
            font_size=22,
            size_hint=(1, 0.08),
            color=(0.15, 0.25, 0.45, 1),
            bold=True
        )
        root.add_widget(title_label)

        # 按钮区
        btn_layout = BoxLayout(size_hint=(1, 0.08), spacing=20)
        self.btn_select = Button(
            text="选择图片",
            font_name=FONT_NAME,
            font_size=16,
            background_color=(0.25, 0.55, 0.85, 1),
            background_normal='',
            color=(1, 1, 1, 1),
            size_hint=(0.4, 1)
        )
        self.btn_select.bind(on_press=self.open_filechooser)

        self.btn_analyze = Button(
            text="开始分析",
            font_name=FONT_NAME,
            font_size=16,
            background_color=(0.3, 0.7, 0.45, 1),
            background_normal='',
            color=(1, 1, 1, 1),
            size_hint=(0.4, 1),
            disabled=True
        )
        self.btn_analyze.bind(on_press=self.analyze_image)

        btn_layout.add_widget(self.btn_select)
        btn_layout.add_widget(self.btn_analyze)
        root.add_widget(btn_layout)

        # 图片预览区
        preview_card = StyledBoxLayout(orientation='vertical', size_hint=(1, 0.45), padding=10, bg_color=(1, 1, 1, 1))
        preview_label = Label(
            text="图片预览",
            font_name=FONT_NAME,
            font_size=14,
            size_hint=(1, 0.1),
            color=(0.3, 0.3, 0.3, 1),
            halign='left',
            valign='middle'
        )
        preview_label.bind(size=preview_label.setter('text_size'))
        preview_card.add_widget(preview_label)

        self.image_widget = KivyImage(size_hint=(1, 0.9), fit_mode='contain')
        preview_card.add_widget(self.image_widget)
        root.add_widget(preview_card)

        # 结果区
        result_card = StyledBoxLayout(orientation='vertical', size_hint=(1, 0.39), padding=15, bg_color=(1, 1, 1, 1))
        result_title = Label(
            text="分析结果",
            font_name=FONT_NAME,
            font_size=14,
            size_hint=(1, 0.1),
            color=(0.3, 0.3, 0.3, 1),
            halign='left',
            valign='middle'
        )
        result_title.bind(size=result_title.setter('text_size'))
        result_card.add_widget(result_title)

        scroll = ScrollView(size_hint=(1, 0.9))
        self.result_label = Label(
            text="请选择图片后点击「开始分析」按钮",
            font_name=FONT_NAME,
            font_size=13,
            size_hint_y=None,
            halign='left',
            valign='top',
            color=(0.2, 0.2, 0.2, 1),
            line_height=1.6
        )
        self.result_label.bind(texture_size=self.result_label.setter('size'))
        scroll.add_widget(self.result_label)
        result_card.add_widget(scroll)
        root.add_widget(result_card)

        self.current_image_path = None
        self.original_img = None
        self.img_small = None
        self.full_size = None
        return root

    def open_filechooser(self, instance):
        content = FileChooserListView(filters=['*.jpg', '*.jpeg', '*.png', '*.bmp', '*.BMP'])
        popup = Popup(title="选择图片", content=content, size_hint=(0.9, 0.9))
        content.bind(on_submit=lambda instance, selection, _: self.load_selected(selection, popup))
        popup.open()

    def load_selected(self, selection, popup):
        popup.dismiss()
        if not selection:
            return
        filepath = selection[0]
        try:
            self.original_img, self.img_small, self.full_size = ImageQualityAnalyzer.load_image(filepath, max_size=1200)
            tmp_path = os.path.join(self.user_data_dir, "temp_preview.jpg")
            cv2.imencode('.jpg', self.img_small)[1].tofile(tmp_path)
            self.image_widget.source = tmp_path
            self.image_widget.reload()
            self.current_image_path = filepath
            self.btn_analyze.disabled = False
            self.result_label.text = f"已加载图片：{os.path.basename(filepath)}\n原始尺寸：{self.full_size[0]} × {self.full_size[1]} 像素\n\n点击「开始分析」查看画质评分"
        except Exception as e:
            self.result_label.text = f"加载失败：{str(e)}"
            self.btn_analyze.disabled = True

    def analyze_image(self, instance):
        if self.img_small is None:
            return
        self.result_label.text = "正在分析中，请稍候..."
        Clock.schedule_once(self._run_analysis, 0.1)

    def _run_analysis(self, dt):
        try:
            start = cv2.getTickCount()
            result = ImageQualityAnalyzer.evaluate(self.img_small)
            end = cv2.getTickCount()
            elapsed = (end - start) / cv2.getTickFrequency() * 1000

            text = f"综合画质评分：{result['total']} 分（满分 100）\n"
            text += f"整体评价：{result['desc']}\n"
            text += f"分析耗时：{elapsed:.0f} 毫秒\n"
            text += "----------------------------------------\n"
            text += "【清晰度】 拉普拉斯方差法\n"
            text += f"    原始值：{result['sharpness_raw']:.3f}    归一化得分：{result['sharpness_norm']:.3f}\n\n"
            text += "【曝光评估】 直方图统计法\n"
            text += f"    归一化得分：{result['exposure_norm']:.3f}\n"
            text += f"    过曝像素占比：{result['overexposed_ratio']:.1%}\n"
            text += f"    欠曝像素占比：{result['underexposed_ratio']:.1%}\n"
            text += f"    画面平均亮度：{result['mean_brightness']:.1f}\n\n"
            text += "【噪点评估】 中值滤波残差法\n"
            text += f"    归一化得分：{result['noise_norm']:.3f}\n"
            text += f"    噪声方差估计：{result['noise_variance']:.3f}"

            self.result_label.text = text
        except Exception as e:
            self.result_label.text = f"分析出错：{str(e)}"

if __name__ == '__main__':
    ImageQualityApp().run()