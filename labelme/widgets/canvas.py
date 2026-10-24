from qtpy import QtCore
from qtpy import QtGui
from qtpy import QtWidgets
from qtpy.QtCore import QTimer

from labelme import QT5
from labelme.shape import Shape, MultipoinstShape, MaskShape
import labelme.utils
import numpy as np
import time
import cv2
import appdirs
import os
import torch
import gc

# 光标类型定义
CURSOR_DEFAULT = QtCore.Qt.ArrowCursor
CURSOR_POINT = QtCore.Qt.PointingHandCursor
CURSOR_DRAW = QtCore.Qt.CrossCursor
CURSOR_MOVE = QtCore.Qt.ClosedHandCursor
CURSOR_GRAB = QtCore.Qt.OpenHandCursor

# 移动速度常量
MOVE_SPEED = 5.0
MIDDLE_DRAG_SPEED = 0.5
WHEEL_SCROLL_SPEED = 0.3

class Canvas(QtWidgets.QWidget):
    CANVAS_PADDING = 100
    # 信号定义
    zoomRequest = QtCore.Signal(int, QtCore.QPoint)
    scrollRequest = QtCore.Signal(int, int)
    newShape = QtCore.Signal()
    selectionChanged = QtCore.Signal(list)
    shapeMoved = QtCore.Signal()
    drawingPolygon = QtCore.Signal(bool)
    vertexSelected = QtCore.Signal(bool)

    # 模式定义
    CREATE, EDIT = 0, 1

    _createMode = "polygon"
    _fill_drawing = False

    def __init__(self, *args, **kwargs):
        # 初始化基础参数
        self.epsilon = kwargs.pop("epsilon", 10.0)
        self.double_click = kwargs.pop("double_click", "close")
        if self.double_click not in [None, "close"]:
            raise ValueError(f"Unexpected double_click value: {self.double_click}")
        kwargs.pop("num_backups", 10)  # 兼容参数 无报错
        self._crosshair = kwargs.pop(
            "crosshair",
            {
                "polygon": False,
                "rectangle": True,
                "circle": False,
                "line": False,
                "point": False,
                "linestrip": False,
                "polygonSAM": False,
                "rectangleSAM": True,
            },
        )
        self.sam_config = kwargs.pop(
            "sam",
            {
                "maxside":2048,
                "approxpoly_epsilon": 0.1,
                "weights": "vit-h",
                "device": "cuda" if torch.cuda.is_available() else "cpu",  # 自动检测设备
                "min_area": 30,
            }
        )
        # 自定义参数：提取后传给父类QWidget会报错
        self.ctrl_snap_multiplier = kwargs.pop("ctrl_snap_multiplier", 3.0)
        self.vertex_highlight_size = kwargs.pop("vertex_highlight_size", 2)
        # 权重不可用时的原因（供状态栏 / 提示框使用），None 表示尚未尝试或已就绪
        self._sam_error = None
        self._sam_warned = False
        super(Canvas, self).__init__(*args, **kwargs)
        
        # 动态ε值配置 无上限下限
        self.dynamic_approx_epsilon = self.sam_config["approxpoly_epsilon"]
        self.epsilon_step = {"increase": 0.05, "decrease": 0.01}

        # ε值悬浮显示标签
        self.epsilon_label = QtWidgets.QLabel(self)
        self.epsilon_label.setStyleSheet("""
            QLabel {
                background-color: rgba(0, 0, 0, 0.7);
                color: white;
                font-size: 12px;
                padding: 2px 5px;
                border-radius: 3px;
            }
        """)
        self.epsilon_label.setAlignment(QtCore.Qt.AlignCenter)
        self.epsilon_label.move(self.width() - 120, 10)
        self._update_epsilon_label()

        # 基础属性初始化
        self.mode = self.EDIT
        self.shapes = []
        self.shapesBackups = []
        self.current = None
        self.selectedShapes = []
        self.selectedShapesCopy = []
        self.line = Shape()
        self.prevPoint = QtCore.QPoint()
        self.prevMovePoint = QtCore.QPoint()
        self.offsets = QtCore.QPoint(), QtCore.QPoint()
        self.scale = 1.0
        self.pixmap = QtGui.QPixmap()
        self.visible = {}
        self._hideBackround = False
        self.hideBackround = False
        self.hShape = None
        self.prevhShape = None
        self.hVertex = None
        self.prevhVertex = None
        self.hEdge = None
        self.prevhEdge = None
        self.movingShape = False
        self.snapping = True
        self._create_snap_enabled = False  # 创建时S键顶点吸附
        self.hShapeIsSelected = False
        self._painter = QtGui.QPainter()
        self._cursor = CURSOR_DEFAULT
        self.menus = (QtWidgets.QMenu(), QtWidgets.QMenu())
        self.setMouseTracking(True)
        self.setFocusPolicy(QtCore.Qt.WheelFocus)
        self.sam_predictor = None
        self.sam_mask = MaskShape()
        self.sam_image_scale = 1.0  # 初始化缩放比例
        
        # Shift框选顶点相关变量
        self._is_dragging_selection = False
        self._selection_rect = QtCore.QRectF()
        self._selected_vertices = []

        # PS式自由手绘选区相关变量
        self._is_dragging_free_select = False
        self._free_select_points = []
        self._free_select_min_points = 5

        self._is_middle_dragging = False
        self._prev_middle_pos = QtCore.QPoint()

    def _update_epsilon_label(self):
        text = f"SAM多边形精度ε: {self.dynamic_approx_epsilon:.3f}"
        self.epsilon_label.setText(text)
        self.epsilon_label.move(self.width() - self.epsilon_label.width() - 10, 10)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._update_epsilon_label()

    def _merge_adjacent_polygons(self, shape1, shape2):
        if shape1.shape_type != "polygon" or shape2.shape_type != "polygon":
            print("仅支持合并多边形类型！")
            return None
        
        pts1 = np.array([[p.x(), p.y()] for p in shape1.points], dtype=np.float32)
        pts2 = np.array([[p.x(), p.y()] for p in shape2.points], dtype=np.float32)
        
        try:
            combined_pts = np.vstack([pts1, pts2])
            hull = cv2.convexHull(combined_pts)
            merged_points = [QtCore.QPointF(p[0][0], p[0][1]) for p in hull]
            merged_shape = Shape(shape_type="polygon")
            merged_shape.label = shape1.label
            merged_shape.flags = shape1.flags
            merged_shape.points = merged_points
            merged_shape.close()
            
            for s in self.shapes:
                s.selected = False
            self.selectedShapes = []
            self.selectionChanged.emit([])
            
            self.shapes.remove(shape1)
            self.shapes.remove(shape2)
            self.shapes.append(merged_shape)
            
            self.selectionChanged.emit([])
            self.storeShapes()
            
            def select_new_shape():
                merged_shape.selected = True
                self.selectedShapes = [merged_shape]
                self.selectionChanged.emit([merged_shape])
                self.update()
            
            QTimer.singleShot(50, select_new_shape)
            print(f"成功合并多边形！合并后顶点数：{len(merged_shape.points)}")
            return merged_shape
        except Exception as e:
            print(f"合并多边形失败：{str(e)}")
            return None

    def adjust_selected_polygon_vertex_density(self):
        if not self.selectedShapes:
            print("未选中多边形！")
            return False
        
        if self.pixmap.isNull():
            print("未加载图片！")
            return False
        
        min_area = self.sam_config.get("min_area", 30)
        success_count = 0
        
        for shape in self.selectedShapes:
            if shape.shape_type != "polygon":
                print(f"跳过非多边形：{shape.shape_type}")
                continue
            
            try:
                img_h, img_w = self.pixmap.height(), self.pixmap.width()
                mask = np.zeros((img_h, img_w), dtype=np.uint8)
                poly_pts = np.array([[int(p.x()), int(p.y())] for p in shape.points], dtype=np.int32)
                cv2.fillPoly(mask, [poly_pts], 255)
                
                temp_mask_shape = MaskShape()
                temp_mask_shape.setScaleMask(1.0, mask)
                
                polygons = temp_mask_shape.toPolygons(self.dynamic_approx_epsilon)
                if len(polygons) == 0:
                    print("掩码转多边形失败！")
                    continue
                
                valid_polygons = []
                for poly in polygons:
                    pts = np.array([[p.x(), p.y()] for p in poly.points], dtype=np.float32)
                    area = cv2.contourArea(pts)
                    if area < 0:
                        pts = pts[::-1]
                    if area > min_area:
                        valid_polygons.append(poly)
                
                if len(valid_polygons) == 0:
                    print("无有效多边形（面积过小）！")
                    continue
                
                new_poly = valid_polygons[0]
                old_point_count = len(shape.points)
                shape.points = new_poly.points
                shape.close()
                
                success_count += 1
                print(f"多边形调整完成：顶点数 {old_point_count} → {len(shape.points)}")
                
            except Exception as e:
                print(f"调整失败：{str(e)}")
                continue
        
        if success_count > 0:
            self.storeShapes()
            self.shapeMoved.emit()
            self.update()
            return True
        return False

    def setLastLabel(self, text, flags):
        assert text
        self.shapes[-1].label = text
        self.shapes[-1].flags = flags
        polygons = None
        if isinstance(self.shapes[-1], MaskShape):
            mask_shape = self.shapes.pop()
            if mask_shape in self.selectedShapes:
                self.selectedShapes.remove(mask_shape)
            polygons = mask_shape.toPolygons(self.dynamic_approx_epsilon)
            min_area = self.sam_config.get("min_area", 30)
            valid_polygons = []
            for poly in polygons:
                pts = np.array([[p.x(), p.y()] for p in poly.points], dtype=np.float32)
                area = cv2.contourArea(pts)
                if area < 0:
                    pts = pts[::-1]
                if area > min_area:
                    ordered_points = [QtCore.QPointF(p[0], p[1]) for p in pts]
                    poly.points = ordered_points
                    valid_polygons.append(poly)
            polygons = valid_polygons
            self.shapes.extend(polygons)
        self.shapesBackups.pop()
        self.storeShapes()

        if isinstance(polygons, list):
            return polygons
        else:
            return self.shapes[-1:]

    def fillDrawing(self):
        return self._fill_drawing

    def setFillDrawing(self, value):
        self._fill_drawing = value

    # 核心快捷键
    def keyPressEvent(self, ev):
        modifiers = ev.modifiers()
        key = ev.key()

        # Ctrl + ` 组合键 → SAM精准矩形模式
        if key == QtCore.Qt.Key_QuoteLeft and modifiers == QtCore.Qt.ControlModifier:
            self.createMode = "rectangleSAM"
            self.setEditing(False)
            self.current = None
            if not self.current:
                self.current = MultipoinstShape()
            self.overrideCursor(CURSOR_DRAW)
            self.drawingPolygon.emit(True)
            self.update()
            print("已进入【HQ-SAM精准矩形框】模式 → 左键=前景点 右键=背景点 Ctrl+回车/3键=生成矩形")
            return

        # 单按 ` 键 → SAM多边形模式
        elif key == QtCore.Qt.Key_QuoteLeft:
            self.createMode = "polygonSAM"
            self.setEditing(False)
            self.current = None
            if not self.current:
                self.current = MultipoinstShape()
            self.overrideCursor(CURSOR_DRAW)
            self.drawingPolygon.emit(True)
            self.update()
            return

        elif key == QtCore.Qt.Key_1:
            self.createMode = "polygon"
            self.setEditing(False)
            if not self.current:
                self.current = Shape(shape_type="polygon")
            self.overrideCursor(CURSOR_DRAW)
            self.drawingPolygon.emit(True)
            self.update()
            return

        elif key == QtCore.Qt.Key_2:
            self.setEditing(True)
            self.unHighlight()
            self.selectedShapes = []
            self.selectionChanged.emit([])
            if self._cursor != CURSOR_POINT:
                self.overrideCursor(CURSOR_POINT)
            self.update()
            return

        elif key == QtCore.Qt.Key_3:
            if (self.createMode == "polygonSAM" or self.createMode == "rectangleSAM") and self.canCloseShape():
                self.finalise()
            return

        elif key == QtCore.Qt.Key_4:
            if self._selected_vertices:
                self._delete_selected_vertices()
            elif self.prevhShape and self.prevhVertex is not None:
                self.removeSelectedPoint()
            self.update()
            return

        elif key == QtCore.Qt.Key_5:
            if len(self.selectedShapes) == 2:
                shape1, shape2 = self.selectedShapes
                merged_shape = self._merge_adjacent_polygons(shape1, shape2)
                if merged_shape:
                    self.storeShapes()
                    self.update()
                else:
                    print("合并失败：请选择两个相邻的多边形！")
            else:
                print("合并失败：请先选中且仅选中两个多边形！")
            return

        elif key == QtCore.Qt.Key_6:
            self.dynamic_approx_epsilon += self.epsilon_step["increase"]
            self._update_epsilon_label()
            print(f"当前多边形精度ε：{self.dynamic_approx_epsilon:.3f}（点更少）")
            if self.createMode == "polygonSAM" and self.sam_mask:
                self.update()
            return

        elif key == QtCore.Qt.Key_7:
            self.dynamic_approx_epsilon -= self.epsilon_step["decrease"]
            self._update_epsilon_label()
            print(f"当前多边形精度ε：{self.dynamic_approx_epsilon:.3f}（点更多）")
            if self.createMode == "polygonSAM" and self.sam_mask:
                self.update()
            return

        elif key == QtCore.Qt.Key_0:
            if self.editing():
                self.adjust_selected_polygon_vertex_density()
            return

        if self.drawing():
            if key == QtCore.Qt.Key_Escape and self.current:
                self.current = None
                self.drawingPolygon.emit(False)
                self.update()
            elif (self.createMode == "polygonSAM" or self.createMode == "rectangleSAM") and key == QtCore.Qt.Key_Return and self.canCloseShape():
                self.finalise()
            elif key == QtCore.Qt.Key_S and self.drawing():
                self._create_snap_enabled = True
            elif modifiers == QtCore.Qt.AltModifier:
                self.snapping = False
        elif self.editing():
            if key == QtCore.Qt.Key_Up:
                self.moveByKeyboard(QtCore.QPointF(0.0, -1.0))
            elif key == QtCore.Qt.Key_Down:
                self.moveByKeyboard(QtCore.QPointF(0.0, 1.0))
            elif key == QtCore.Qt.Key_Left:
                self.moveByKeyboard(QtCore.QPointF(-1.0, 0.0))
            elif key == QtCore.Qt.Key_Right:
                self.moveByKeyboard(QtCore.QPointF(1.0, 0.0))

    # HQ-SAM矩形生成核心逻辑
    def finalise(self):
        assert self.current
        self.current.close()
        if self.createMode == 'polygonSAM':
            self.shapes.append(self.sam_mask)
        elif self.createMode == 'rectangleSAM':
            mask = getattr(self.sam_mask, 'mask', None)
            if mask is None or mask.sum() == 0:
                print("HQ-SAM 生成的掩码为空，无法创建矩形")
                self.current = None
                self.sam_mask = MaskShape()
                return
            contours, _ = cv2.findContours(mask.astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            if len(contours) == 0:
                print("未检测到掩码轮廓，无法创建矩形")
                self.current = None
                self.sam_mask = MaskShape()
                return
            max_contour = max(contours, key=cv2.contourArea)
            x, y, w, h = cv2.boundingRect(max_contour)
            rect_shape = Shape(shape_type="rectangle")
            rect_shape.points = [QtCore.QPointF(x, y), QtCore.QPointF(x + w, y + h)]
            rect_shape.close()
            self.shapes.append(rect_shape)
            print(f"HQ-SAM 矩形生成成功 → 位置：({x},{y}) 尺寸：{w}×{h}")
        else:
            self.shapes.append(self.current)
        self.storeShapes()
        self.sam_mask = MaskShape()
        self.current = None
        self.setHiding(False)
        self.newShape.emit()
        self.update()

    @property
    def createMode(self):
        return self._createMode

    @createMode.setter
    def createMode(self, value):
        if value not in [
            "polygon", "rectangle", "circle", "line", "point", "linestrip", 
            "polygonSAM", "rectangleSAM"
        ]:
            raise ValueError(f"Unsupported createMode: {value}")
        self._createMode = value
        self.sam_mask = MaskShape()
        self.current = None
        if value == "polygonSAM" or value == "rectangleSAM":
            self.loadSamPredictor()
            if self.sam_predictor is None:
                # 权重不可用：退回普通多边形，并提示一次，别让用户以为软件坏了
                self._createMode = "polygon"
                if not getattr(self, "_sam_warned", False):
                    self._sam_warned = True
                    QtWidgets.QMessageBox.warning(
                        self,
                        "SAM 不可用",
                        "HQ-SAM 权重未就绪，已切换回普通多边形模式。\n"
                        "纯手工标注不受影响。\n\n"
                        "下载权重后重启：\n"
                        "    python download_model.py\n\n"
                        "具体失败原因见命令行窗口。",
                    )

    # ====================== 核心修复：HQ-SAM 模型加载（统一数据类型 + 8GB GPU适配） ======================
    def loadSamPredictor(self):
        if not self.sam_predictor:
            from segment_anything import sam_model_registry, SamPredictor
            cachedir = appdirs.user_cache_dir("labelme")
            os.makedirs(cachedir, exist_ok=True)

            weight_key = self.sam_config["weights"]

            # 权重的查找 / 下载 / 校验统一交给 labelme.sam_weight，顺序是：
            #   1. <项目根>/models/<权重名>                        —— README 让新人放这里
            #   2. %LOCALAPPDATA%/labelme/labelme/Cache/<权重名>   —— 历史手动放置位置
            #   3. appdirs 缓存目录
            #   4. 都没有则按镜像列表联网下载（带进度、支持续传）
            # 拿不到权重时只降级为纯手工标注，不让程序崩。
            try:
                from labelme.sam_weight import SamWeightError, ensure_weight

                weight_file = ensure_weight(weight_key, allow_download=True)
            except SamWeightError as exc:
                print(str(exc))
                self._sam_error = str(exc)
                self.sam_predictor = None
                return
            except Exception as exc:  # 权重档位写错、目录没权限等
                print(f"模型准备失败: {exc}")
                self._sam_error = str(exc)
                self.sam_predictor = None
                return

            # ====================== 显存优化 + 数据类型统一核心 ======================
            # 1. 预清理显存
            torch.cuda.empty_cache()
            gc.collect()
            
            # 2. 设置显存优化参数
            os.environ["PYTORCH_CUDA_ALLOC_CONF"] = "max_split_size_mb:128"
            if torch.cuda.is_available():
                torch.cuda.set_per_process_memory_fraction(0.9, 0)  # 限制使用90%显存
            
            # 3. 加载HQ-SAM模型（强制统一使用float32，彻底解决类型不匹配）
            try:
                model_type = weight_key.replace("-", "_")
                # 第一步：创建空模型结构（不加载权重）
                sam = sam_model_registry[model_type](checkpoint=None)
                # 第二步：读取HQ-SAM权重文件（指定CPU加载，避免显存溢出）
                hq_state_dict = torch.load(weight_file, map_location="cpu")
                # 第三步：加载权重，忽略不识别的新增参数
                sam.load_state_dict(hq_state_dict, strict=False)
                
                # ========== 核心修复1：强制所有参数使用float32 ==========
                sam = sam.to(dtype=torch.float32)
                
                # ========== 设备适配 ==========
                device = self.sam_config["device"]
                if device == "cuda" and torch.cuda.is_available():
                    sam = sam.to(device="cuda")
                else:
                    sam = sam.to(device="cpu")
                    self.sam_config["device"] = "cpu"
                
                # 推理模式，禁用梯度计算
                sam.eval()
                
                # ========== 创建Predictor并强制统一类型 ==========
                self.sam_predictor = SamPredictor(sam)
                # 强制Predictor的模型保持float32
                self.sam_predictor.model = self.sam_predictor.model.to(dtype=torch.float32)
                
            except Exception as e:
                raise RuntimeError(f"模型加载失败: {str(e)}")

            # 最终清理显存
            torch.cuda.empty_cache()
            gc.collect()
            
        self.samEmbedding()

    def samEmbedding(self):
        if self.pixmap.isNull():
            return
            
        image = self.pixmap.toImage().copy()
        img_size = image.size()
        s = image.bits().asstring(img_size.height() * img_size.width() * image.depth()//8)
        image = np.frombuffer(s, dtype=np.uint8).reshape([img_size.height(), img_size.width(), image.depth()//8])
        if image.shape[2] == 1:
            image = cv2.cvtColor(image, cv2.COLOR_GRAY2RGB)
        elif image.shape[2] == 4:
            image = cv2.cvtColor(image, cv2.COLOR_RGBA2RGB)
        image = image[:,:,:3].copy()
        h, w, _ = image.shape
        
        # 图片缩放优化（进一步降低显存峰值）
        self.sam_image_scale = self.sam_config["maxside"] / max(h, w)
        self.sam_image_scale = max(0.5, min(1, self.sam_image_scale))
        image = cv2.resize(image, None, fx=self.sam_image_scale, fy=self.sam_image_scale, interpolation=cv2.INTER_LANCZOS4)
        
        # 推理时禁用梯度
        with torch.no_grad():
            # ========== 核心修复2：设置图片时强制统一类型 ==========
            self.sam_predictor.set_image(
                image,
                image_format="RGB"
            )
            # 强制模型输入保持float32
            if hasattr(self.sam_predictor, 'features') and self.sam_predictor.features is not None:
                self.sam_predictor.features = self.sam_predictor.features.to(dtype=torch.float32)
        self.update()

    # ====================== 核心修复3：SAM推理完全兼容原生numpy输入 ======================
    def samPrompt(self, points, labels):
        if self.sam_predictor is None:
            print("SAM Predictor未初始化！")
            return
            
        # 1. 基础数据校验和转换（全程numpy，兼容原生SAM）
        points = np.array(points, dtype=np.float32) if points is not None else np.array([])
        labels = np.array(labels, dtype=np.int32) if labels is not None else np.array([])
        
        # 2. 空值处理
        if len(points) == 0:
            print("SAM提示点为空，跳过推理")
            return
        
        # 3. 推理时禁用梯度
        with torch.no_grad():
            # 准备mask_input（如果有）
            mask_input = None
            if self.sam_mask.logits is not None:
                mask_input = self.sam_mask.logits[None, :, :]
            
            # 坐标缩放（numpy格式）
            points_np = points * self.sam_image_scale
            
            # 原生SAM predict只接受numpy数组！核心修复
            masks, scores, logits = self.sam_predictor.predict(
                point_coords=points_np,
                point_labels=labels,
                mask_input=mask_input,
                multimask_output=False
            )
        
        # 4. 结果处理
        best_idx = 0
        self.sam_mask.logits = logits[best_idx, :, :] if logits is not None else None
        mask = masks[best_idx, :, :]

        # 5. 掩码优化
        kernel = np.ones((2, 2), np.uint8)
        mask = cv2.dilate(mask.astype(np.uint8), kernel, iterations=1)
        # 加强闭运算填充mask中的缝隙：5x5核+2次迭代
        close_kernel = np.ones((5, 5), np.uint8)
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, close_kernel, iterations=2)
        self.sam_mask.setScaleMask(self.sam_image_scale, mask)

    # 无限撤销
    def storeShapes(self):
        shapesBackup = []
        for shape in self.shapes:
            shapesBackup.append(shape.copy())
        self.shapesBackups.append(shapesBackup)

    @property
    def isShapeRestorable(self):
        return len(self.shapesBackups) >= 2

    def restoreShape(self):
        if not self.isShapeRestorable:
            return
        self.shapesBackups.pop()
        shapesBackup = self.shapesBackups.pop()
        self.shapes = shapesBackup
        self.selectedShapes = []
        for shape in self.shapes:
            shape.selected = False
        self.update()

    def enterEvent(self, ev):
        self.overrideCursor(self._cursor)

    def leaveEvent(self, ev):
        self.unHighlight()
        self.restoreCursor()

    def focusOutEvent(self, ev):
        self.restoreCursor()

    def isVisible(self, shape):
        return self.visible.get(shape, True)

    def drawing(self):
        return self.mode == self.CREATE

    def editing(self):
        return self.mode == self.EDIT

    def setEditing(self, value=True):
        self.mode = self.EDIT if value else self.CREATE
        if self.mode == self.EDIT:
            self.repaint()
        else:
            self.unHighlight()
            self.deSelectShape()

    def unHighlight(self):
        if self.hShape:
            self.hShape.highlightClear()
            self.update()
        self.prevhShape = self.hShape
        self.prevhVertex = self.hVertex
        self.prevhEdge = self.hEdge
        self.hShape = self.hVertex = self.hEdge = None

    def selectedVertex(self):
        return self.hVertex is not None

    def selectedEdge(self):
        return self.hEdge is not None

    def _get_vertices_in_rect(self, rect):
        selected_vertices = []
        for shape in self.shapes:
            if not self.isVisible(shape) or shape.shape_type != "polygon":
                continue
            for idx, point in enumerate(shape.points):
                if rect.contains(point):
                    selected_vertices.append((shape, idx))
        return selected_vertices

    def _delete_selected_vertices(self):
        if not self._selected_vertices:
            return
        
        shape_vertices = {}
        for shape, idx in self._selected_vertices:
            if shape not in shape_vertices:
                shape_vertices[shape] = []
            shape_vertices[shape].append(idx)
        
        deleted = False
        for shape, indices in shape_vertices.items():
            if len(shape.points) - len(indices) < 3:
                continue
            for idx in sorted(indices, reverse=True):
                shape.removePoint(idx)
                deleted = True
                self.movingShape = True
        
        if deleted:
            self.storeShapes()
            self.shapeMoved.emit()
        self._selected_vertices = []
        self.update()

    def _is_shape_in_free_select(self, shape):
        if shape.shape_type != "polygon" or not self._free_select_points or len(self._free_select_points) < self._free_select_min_points:
            return False
        rect = shape.boundingRect()
        shape_center = QtCore.QPointF(rect.center().x(), rect.center().y())
        free_select_np = np.array(self._free_select_points, dtype=np.int32).reshape((-1, 1, 2))
        ret = cv2.pointPolygonTest(free_select_np, (shape_center.x(), shape_center.y()), False)
        return ret >= 0

    def _select_shapes_in_free_select(self):
        selected_shapes = []
        for shape in self.shapes:
            if self.isVisible(shape) and self._is_shape_in_free_select(shape):
                selected_shapes.append(shape)
                shape.selected = True
        for s in selected_shapes:
            if s not in self.selectedShapes:
                self.selectedShapes.append(s)
        self.selectionChanged.emit(self.selectedShapes)
        print(f"自由选区选中 {len(selected_shapes)} 个多边形")

    def mouseMoveEvent(self, ev):
        if self._is_middle_dragging and ev.buttons() & QtCore.Qt.MiddleButton:
            current_pos = ev.pos()
            delta_x = current_pos.x() - self._prev_middle_pos.x()
            delta_y = current_pos.y() - self._prev_middle_pos.y()
            
            final_delta_x = delta_x * MIDDLE_DRAG_SPEED
            final_delta_y = delta_y * MIDDLE_DRAG_SPEED
            
            self.scrollRequest.emit(int(final_delta_x), QtCore.Qt.Horizontal)
            self.scrollRequest.emit(int(final_delta_y), QtCore.Qt.Vertical)
            
            self._prev_middle_pos = current_pos
            return

        try:
            if QT5:
                pos = self.transformPos(ev.localPos())
            else:
                pos = self.transformPos(ev.posF())
        except AttributeError:
            return
        self.prevMovePoint = pos
        self.restoreCursor()

        if self._is_dragging_selection and self.editing():
            self._selection_rect.setBottomRight(pos)
            self._selected_vertices = self._get_vertices_in_rect(self._selection_rect)
            self.update()
            return

        if self._is_dragging_free_select and self.editing() and ev.buttons() & QtCore.Qt.LeftButton:
            if not self._free_select_points or (abs(pos.x() - self._free_select_points[-1][0]) > 0.5 or abs(pos.y() - self._free_select_points[-1][1]) > 0.5):
                self._free_select_points.append([int(pos.x()), int(pos.y())])
            self.update()
            return

        if self.drawing():
            self.line.shape_type = "polygon" if self.createMode == "polygonSAM" else "rectangle" if self.createMode == "rectangleSAM" else self.createMode
            self.overrideCursor(CURSOR_DRAW)
            if not self.current:
                if self.createMode == "polygonSAM" or self.createMode == "rectangleSAM":
                    points = np.array([[pos.x(), pos.y()]], dtype=np.float32)
                    labels = np.array([1], dtype=np.int32)
                    self.samPrompt(points, labels)
                self.repaint()
                return

            if self.outOfPixmap(pos):
                pos = self.intersectionPoint(self.current[-1], pos)
            elif (
                self.snapping
                and len(self.current) > 1
                and self.createMode == "polygon"
                and self.closeEnough(pos, self.current[0])
            ):
                pos = self.current[0]
                self.overrideCursor(CURSOR_POINT)
                self.current.highlightVertex(0, Shape.NEAR_VERTEX)
            if self.createMode in ["polygon", "linestrip"]:
                # === 创建模式S键顶点吸附 ===
                if self._create_snap_enabled:
                    snap_dist = self.epsilon * self.ctrl_snap_multiplier / self.scale
                    best_p = None
                    best_d = snap_dist
                    for s in self.shapes:
                        if self.isVisible(s):
                            idx = s.nearestVertex(pos, snap_dist)
                            if idx is not None:
                                d = labelme.utils.distance(s.points[idx] - pos)
                                if d < best_d:
                                    best_d = d
                                    best_p = s.points[idx]
                    if best_p is not None:
                        pos = best_p
                        self.overrideCursor(CURSOR_POINT)
                self.line[0] = self.current[-1]
                self.line[1] = pos
            elif self.createMode == "rectangle":
                self.line.points = [self.current[0], pos]
                self.line.close()
            elif self.createMode == "circle":
                self.line.points = [self.current[0], pos]
                self.line.shape_type = "circle"
            elif self.createMode == "line":
                self.line.points = [self.current[0], pos]
                self.line.close()
            elif self.createMode in "point":
                self.line.points = [self.current[0]]
                self.line.close()
            elif self.createMode == "polygonSAM" or self.createMode == "rectangleSAM":
                self.line.points = [pos, pos]
            self.repaint()
            self.current.highlightClear()
            return

        if QtCore.Qt.RightButton & ev.buttons():
            if self.selectedShapesCopy and self.prevPoint:
                self.overrideCursor(CURSOR_MOVE)
                self.boundedMoveShapes(self.selectedShapesCopy, pos)
                self.repaint()
            elif self.selectedShapes:
                self.selectedShapesCopy = [s.copy() for s in self.selectedShapes]
                self.repaint()
            return

        if QtCore.Qt.LeftButton & ev.buttons():
            if self.selectedVertex():
                self.boundedMoveVertex(pos)
                self.repaint()
                self.movingShape = True
            elif self.selectedShapes and self.prevPoint:
                self.overrideCursor(CURSOR_MOVE)
                self.boundedMoveShapes(self.selectedShapes, pos)
                self.repaint()
                self.movingShape = True
            return

        # Ctrl+hover: highlight nearest vertex from any layer
        if ev.modifiers() & QtCore.Qt.ControlModifier:
            ctrl_dist = self.epsilon * self.ctrl_snap_multiplier / self.scale
            best_idx = None
            best_s = None
            best_d = ctrl_dist
            for s in self.shapes:
                if self.isVisible(s):
                    idx = s.nearestVertex(pos, ctrl_dist)
                    if idx is not None:
                        d = labelme.utils.distance(s.points[idx] - pos)
                        if d < best_d:
                            best_d = d
                            best_idx = idx
                            best_s = s
            if best_s is not None:
                if self.selectedVertex():
                    self.hShape.highlightClear()
                self.hVertex = best_idx
                self.prevhVertex = best_idx
                self.hShape = best_s
                self.prevhShape = best_s
                self.hEdge = None
                best_s.highlightVertex(best_idx, best_s.MOVE_VERTEX)
                self.overrideCursor(CURSOR_POINT)
                self.setToolTip(self.tr("Click & drag to move point"))
                self.setStatusTip(self.toolTip())
                self.update()
                return
        self.setToolTip(self.tr("Image"))
        for shape in reversed([s for s in self.shapes if self.isVisible(s)]):
            index = shape.nearestVertex(pos, self.epsilon / self.scale)
            index_edge = shape.nearestEdge(pos, self.epsilon / self.scale)
            if index is not None:
                if self.selectedVertex():
                    self.hShape.highlightClear()
                self.prevhVertex = self.hVertex = index
                self.prevhShape = self.hShape = shape
                self.prevhEdge = self.hEdge
                self.hEdge = None
                shape.highlightVertex(index, shape.MOVE_VERTEX)
                self.overrideCursor(CURSOR_POINT)
                self.setToolTip(self.tr("Click & drag to move point"))
                self.setStatusTip(self.toolTip())
                self.update()
                break
            elif index_edge is not None and shape.canAddPoint():
                if self.selectedVertex():
                    self.hShape.highlightClear()
                self.prevhVertex = self.hVertex
                self.hVertex = None
                self.prevhShape = self.hShape = shape
                self.prevhEdge = self.hEdge = index_edge
                self.overrideCursor(CURSOR_POINT)
                self.setToolTip(self.tr("Click to create point"))
                self.setStatusTip(self.toolTip())
                self.update()
                break
            elif shape.containsPoint(pos):
                if self.selectedVertex():
                    self.hShape.highlightClear()
                self.prevhVertex = self.hVertex
                self.hVertex = None
                self.prevhShape = self.hShape = shape
                self.prevhEdge = self.hEdge
                self.hEdge = None
                self.setToolTip(self.tr("Click & drag to move shape '%s'") % shape.label)
                self.setStatusTip(self.toolTip())
                self.overrideCursor(CURSOR_GRAB)
                self.update()
                break
        else:
            self.unHighlight()
        self.vertexSelected.emit(self.hVertex is not None)

    def addPointToEdge(self):
        shape = self.prevhShape
        edge_index = self.prevhEdge
        click_point = self.prevMovePoint

        if shape is None or edge_index is None or click_point is None:
            return
        points = shape.points
        if len(points) < 2:
            return

        a = points[edge_index]
        b = points[(edge_index + 1) % len(points)]

        def project_point_to_line(p, a, b):
            ax, ay = a.x(), a.y()
            bx, by = b.x(), b.y()
            px, py = p.x(), p.y()

            abx = bx - ax
            aby = by - ay
            apx = px - ax
            apy = py - ay

            ab_len_sq = abx ** 2 + aby ** 2
            if ab_len_sq == 0:
                return a

            t = (apx * abx + apy * aby) / ab_len_sq
            t = max(0.001, min(0.999, t))

            proj_x = ax + t * abx
            proj_y = ay + t * aby
            return QtCore.QPointF(proj_x, proj_y)

        projected_point = project_point_to_line(click_point, a, b)
        shape.insertPoint(edge_index + 1, projected_point)

        shape.highlightVertex(edge_index + 1, shape.MOVE_VERTEX)
        self.hShape = shape
        self.hVertex = edge_index + 1
        self.hEdge = None
        self.movingShape = True
        self.update()

    def removeSelectedPoint(self):
        shape = self.prevhShape
        index = self.prevhVertex
        if (
                shape is None
                or index is None
                or not shape.points
                or index < 0
                or index >= len(shape.points)
        ):
            return

        shape.removePoint(index)
        shape.highlightClear()

        self.hShape = shape
        self.prevhVertex = None
        self.hVertex = None
        self.movingShape = True

        # 触发保存标记
        self.storeShapes()
        self.shapeMoved.emit()

    def mousePressEvent(self, ev):
        if ev.button() == QtCore.Qt.MiddleButton:
            self._is_middle_dragging = True
            self._prev_middle_pos = ev.pos()
            self.overrideCursor(CURSOR_MOVE)
            return

        if QT5:
            pos = self.transformPos(ev.localPos())
        else:
            pos = self.transformPos(ev.posF())
        
        is_shift_pressed = ev.modifiers() & QtCore.Qt.ShiftModifier
        if ev.button() == QtCore.Qt.LeftButton and self.editing() and is_shift_pressed:
            if not self.selectedVertex() and not self.selectedEdge():
                self._is_dragging_selection = True
                self._selection_rect = QtCore.QRectF(pos, pos)
                self._selected_vertices = []
                self._is_dragging_free_select = False
                self._free_select_points = []
                return

        is_ctrl_pressed = ev.modifiers() & QtCore.Qt.ControlModifier
        if ev.button() == QtCore.Qt.LeftButton and self.editing() and is_ctrl_pressed:
            if not self.selectedVertex() and not self.selectedEdge():
                self._is_dragging_selection = False
                self._selection_rect = QtCore.QRectF()
                self._selected_vertices = []
                self._is_dragging_free_select = True
                self._free_select_points = [[int(pos.x()), int(pos.y())]]
                return

        if ev.button() == QtCore.Qt.LeftButton:
            if self.drawing():
                if self.current:
                    if self.createMode == "polygon":
                        # S键创建吸附：点击时确认吸附位置
                        if self._create_snap_enabled:
                            sp = None; sd = self.epsilon * self.ctrl_snap_multiplier / self.scale
                            for s in self.shapes:
                                if self.isVisible(s):
                                    idx = s.nearestVertex(self.line[1], sd)
                                    if idx is not None:
                                        d = labelme.utils.distance(s.points[idx] - self.line[1])
                                        if d < sd: sd = d; sp = s.points[idx]
                            if sp: self.line[1] = sp; self.line[0] = sp
                        self.current.addPoint(self.line[1])
                        self.line[0] = self.current[-1]
                        if self.current.isClosed():
                            self.finalise()
                    elif self.createMode in ["rectangle", "circle", "line"]:
                        assert len(self.current.points) == 1
                        self.current.points = self.line.points
                        self.finalise()
                    elif self.createMode == "linestrip":
                        self.current.addPoint(self.line[1])
                        self.line[0] = self.current[-1]
                        if int(ev.modifiers()) == QtCore.Qt.ControlModifier:
                            self.finalise()
                    elif self.createMode == "polygonSAM" or self.createMode == "rectangleSAM":
                        self.current.addPoint(self.line[1], True)
                        points = [[point.x(), point.y()] for point in self.current.points]
                        labels = [int(label) for label in self.current.labels]
                        self.samPrompt(np.array(points), np.array(labels))
                        if int(ev.modifiers()) == QtCore.Qt.ControlModifier:
                            self.finalise()
                elif not self.outOfPixmap(pos):
                    if self.createMode != "polygonSAM" and self.createMode != "rectangleSAM":
                        self.current = Shape(shape_type=self.createMode)
                        self.current.addPoint(pos)
                    else:
                        self.current = MultipoinstShape()
                        self.current.addPoint(pos, True)
                    if self.createMode == "point":
                        self.finalise()
                    else:
                        if self.createMode == "circle":
                            self.current.shape_type = "circle"
                        self.line.points = [pos, pos]
                        self.setHiding()
                        self.drawingPolygon.emit(True)
                        self.update()
            elif self.editing():
                if self.selectedEdge():
                    self.addPointToEdge()
                elif (
                    self.selectedVertex()
                    and int(ev.modifiers()) == QtCore.Qt.ShiftModifier
                ):
                    self.removeSelectedPoint()

                group_mode = int(ev.modifiers()) == QtCore.Qt.ControlModifier
                self.selectShapePoint(pos, multiple_selection_mode=group_mode)
                if self.selectedVertex() and group_mode:
                    self.prevPoint = self.hShape[self.hVertex]
                else:
                    self.prevPoint = pos
                self.repaint()
        elif ev.button() == QtCore.Qt.RightButton:
            if self.drawing() and (self.createMode == "polygonSAM" or self.createMode == "rectangleSAM"):
                if self.current:
                    self.current.addPoint(self.line[1], False)
                    points = [[point.x(), point.y()] for point in self.current.points]
                    labels = [int(label) for label in self.current.labels]
                    self.samPrompt(np.array(points), np.array(labels))
                    if int(ev.modifiers()) == QtCore.Qt.ControlModifier:
                        self.finalise()
                elif not self.outOfPixmap(pos):
                    self.current = MultipoinstShape()
                    self.current.addPoint(pos, False)
                    self.line.points = [pos, pos]
                    self.setHiding()
                    self.drawingPolygon.emit(True)
                    self.update()
            elif self.editing():
                group_mode = int(ev.modifiers()) == QtCore.Qt.ControlModifier
                if not self.selectedShapes or (
                    self.hShape is not None
                    and self.hShape not in self.selectedShapes
                ):
                    self.selectShapePoint(pos, multiple_selection_mode=group_mode)
                    self.repaint()
                self.prevPoint = pos

    def mouseReleaseEvent(self, ev):
        if ev.button() == QtCore.Qt.MiddleButton:
            self._is_middle_dragging = False
            self.restoreCursor()
            return

        if ev.button() == QtCore.Qt.LeftButton:
            if self._is_dragging_selection:
                self._is_dragging_selection = False
                self.update()
                return

        if ev.button() == QtCore.Qt.LeftButton:
            if self._is_dragging_free_select:
                self._is_dragging_free_select = False
                if len(self._free_select_points) >= self._free_select_min_points:
                    self._select_shapes_in_free_select()
                    self.storeShapes()
                self._free_select_points = []
                self.update()
                return

        if ev.button() == QtCore.Qt.RightButton:
            if self.createMode not in ['polygonSAM', 'rectangleSAM']:
                menu = self.menus[len(self.selectedShapesCopy) > 0]
                self.restoreCursor()
                if (
                    not menu.exec_(self.mapToGlobal(ev.pos()))
                    and self.selectedShapesCopy
                ):
                    self.selectedShapesCopy = []
                    self.repaint()
        elif ev.button() == QtCore.Qt.LeftButton:
            if self.editing():
                if (
                    self.hShape is not None
                    and self.hShapeIsSelected
                    and not self.movingShape
                ):
                    self.selectionChanged.emit(
                        [x for x in self.selectedShapes if x != self.hShape]
                    )

        if self.movingShape and self.hShape:
            index = self.shapes.index(self.hShape)
            if (
                self.shapesBackups[-1][index].points
                != self.shapes[index].points
            ):
                self.storeShapes()
                self.shapeMoved.emit()

            self.movingShape = False

    def endMove(self, copy):
        assert self.selectedShapes and self.selectedShapesCopy
        assert len(self.selectedShapesCopy) == len(self.selectedShapes)
        if copy:
            for i, shape in enumerate(self.selectedShapesCopy):
                self.shapes.append(shape)
                self.selectedShapes[i].selected = False
                self.selectedShapes[i] = shape
        else:
            for i, shape in enumerate(self.selectedShapesCopy):
                self.selectedShapes[i].points = shape.points
        self.selectedShapesCopy = []
        self.repaint()
        self.storeShapes()
        return True

    def hideBackroundShapes(self, value):
        self.hideBackround = value
        if self.selectedShapes:
            self.setHiding(True)
            self.update()

    def setHiding(self, enable=True):
        self._hideBackround = self.hideBackround if enable else False

    def canCloseShape(self):
        if self.createMode == "polygonSAM" or self.createMode == "rectangleSAM":
            return self.drawing() and self.current and len(self.current) > 0
        return self.drawing() and self.current and len(self.current) > 2

    def mouseDoubleClickEvent(self, ev):
        return

    def selectShapes(self, shapes):
        self.setHiding()
        self.selectionChanged.emit(shapes)
        self.update()

    def selectShapePoint(self, point, multiple_selection_mode):
        # Ctrl mode: search ALL layers for nearest vertex/edge
        if multiple_selection_mode:
            ctrl_dist = self.epsilon * self.ctrl_snap_multiplier / self.scale
            best_idx = None
            best_s = None
            best_d = ctrl_dist
            best_is_vertex = False
            for s in self.shapes:
                if self.isVisible(s):
                    # Check vertices
                    idx = s.nearestVertex(point, ctrl_dist)
                    if idx is not None:
                        d = labelme.utils.distance(s.points[idx] - point)
                        if d < best_d:
                            best_d = d
                            best_idx = idx
                            best_s = s
                            best_is_vertex = True
                    # Also check edges
                    edge_idx = s.nearestEdge(point, ctrl_dist)
                    if edge_idx is not None and not best_is_vertex:
                        n_pts = len(s.points)
                        a = s.points[edge_idx]
                        b = s.points[(edge_idx + 1) % n_pts]
                        ap_x = point.x() - a.x()
                        ap_y = point.y() - a.y()
                        ab_x = b.x() - a.x()
                        ab_y = b.y() - a.y()
                        ab_sq = ab_x * ab_x + ab_y * ab_y
                        if ab_sq > 0:
                            t = max(0.0, min(1.0, (ap_x * ab_x + ap_y * ab_y) / ab_sq))
                            cp_x = a.x() + t * ab_x
                            cp_y = a.y() + t * ab_y
                            d = labelme.utils.distance(QtCore.QPointF(cp_x, cp_y) - point)
                            if d < best_d:
                                best_d = d
                                best_idx = edge_idx
                                best_s = s
                                best_is_vertex = False
            if best_s is not None:
                self.setHiding()
                if best_s not in self.selectedShapes:
                    self.selectionChanged.emit([best_s])
                else:
                    self.hShapeIsSelected = True
                self.hShape = best_s
                if best_is_vertex:
                    self.hVertex = best_idx
                    self.hEdge = None
                else:
                    self.hVertex = None
                    self.hEdge = best_idx
                self.calculateOffsets(point)
            return
        if self.selectedVertex():
            index, shape = self.hVertex, self.hShape
            shape.highlightVertex(index, shape.MOVE_VERTEX)
        else:
            for shape in reversed(self.shapes):
                if self.isVisible(shape) and shape.containsPoint(point):
                    self.setHiding()
                    if shape not in self.selectedShapes:
                        if multiple_selection_mode:
                            self.selectionChanged.emit(self.selectedShapes + [shape])
                        else:
                            self.selectionChanged.emit([shape])
                        self.hShapeIsSelected = False
                    else:
                        self.hShapeIsSelected = True
                    self.calculateOffsets(point)
                    return
        self.deSelectShape()

    def calculateOffsets(self, point):
        left = self.pixmap.width() - 1
        right = 0
        top = self.pixmap.height() - 1
        bottom = 0
        for s in self.selectedShapes:
            rect = s.boundingRect()
            if rect.left() < left:
                left = rect.left()
            if rect.right() > right:
                right = rect.right()
            if rect.top() < top:
                top = rect.top()
            if rect.bottom() > bottom:
                bottom = rect.bottom()

        x1 = left - point.x()
        y1 = top - point.y()
        x2 = right - point.x()
        y2 = bottom - point.y()
        self.offsets = QtCore.QPointF(x1, y1), QtCore.QPointF(x2, y2)

    def boundedMoveVertex(self, pos):
        index, shape = self.hVertex, self.hShape
        point = shape[index]
        if self.outOfPixmap(pos):
            pos = self.intersectionPoint(point, pos)
        # Ctrl+drag: snap vertex to nearest vertex from any layer
        snap_dist = self.epsilon * self.ctrl_snap_multiplier / self.scale
        if QtCore.Qt.ControlModifier & QtWidgets.QApplication.keyboardModifiers():
            nearest_pos = None
            nearest_d = snap_dist
            for s in self.shapes:
                for j, v in enumerate(s.points):
                    if s == shape and j == index:
                        continue
                    d = labelme.utils.distance(pos - v)
                    if d < nearest_d:
                        nearest_d = d
                        nearest_pos = v
            if nearest_pos is not None:
                pos = nearest_pos
        shape.moveVertexBy(index, pos - point)
    def boundedMoveShapes(self, shapes, pos):
        if self.outOfPixmap(pos):
            return False
        o1 = pos + self.offsets[0]
        if self.outOfPixmap(o1):
            pos -= QtCore.QPointF(min(0, o1.x()), min(0, o1.y()))
        o2 = pos + self.offsets[1]
        if self.outOfPixmap(o2):
            pos += QtCore.QPointF(
                min(0, self.pixmap.width() - o2.x()),
                min(0, self.pixmap.height() - o2.y()),
            )
        dp = pos - self.prevPoint
        if dp:
            for shape in shapes:
                shape.moveBy(dp)
            self.prevPoint = pos
            return True
        return False

    def deSelectShape(self):
        if self.selectedShapes:
            self.setHiding(False)
            self.selectionChanged.emit([])
            self.hShapeIsSelected = False
            self.update()

    def deleteSelected(self):
        deleted_shapes = []
        if self.selectedShapes:
            for shape in self.selectedShapes:
                self.shapes.remove(shape)
                deleted_shapes.append(shape)
            self.storeShapes()
            self.selectedShapes = []
            self.update()
        return deleted_shapes

    def deleteShape(self, shape):
        if shape in self.selectedShapes:
            self.selectedShapes.remove(shape)
        if shape in self.shapes:
            self.shapes.remove(shape)
        self.storeShapes()
        self.update()

    def duplicateSelectedShapes(self):
        if self.selectedShapes:
            self.selectedShapesCopy = [s.copy() for s in self.selectedShapes]
            self.boundedShiftShapes(self.selectedShapesCopy)
            self.endMove(copy=True)
        return self.selectedShapes

    def boundedShiftShapes(self, shapes):
        point = shapes[0][0]
        offset = QtCore.QPointF(2.0, 2.0)
        self.offsets = QtCore.QPoint(), QtCore.QPoint()
        self.prevPoint = point
        if not self.boundedMoveShapes(shapes, point - offset):
            self.boundedMoveShapes(shapes, point + offset)

    def paintEvent(self, event):
        if not self.pixmap:
            return super(Canvas, self).paintEvent(event)

        p = self._painter
        p.begin(self)
         # 空白区浅灰色背景（和新版LabelMe一致）
        p.fillRect(self.rect(), QtGui.QColor(245, 245, 245))
        p.setRenderHint(QtGui.QPainter.Antialiasing)
        p.setRenderHint(QtGui.QPainter.HighQualityAntialiasing)
        p.setRenderHint(QtGui.QPainter.SmoothPixmapTransform)

        p.scale(self.scale, self.scale)
        p.translate(self.offsetToCenter())

        p.drawPixmap(0, 0, self.pixmap)
        self.sam_mask.paint(p)

        if self._is_dragging_selection and not self._selection_rect.isEmpty():
            selection_pen = QtGui.QPen(QtGui.QColor(255, 0, 0, 180), 1 / self.scale)
            selection_brush = QtGui.QBrush(QtGui.QColor(255, 0, 0, 30))
            p.setPen(selection_pen)
            p.setBrush(selection_brush)
            p.drawRect(self._selection_rect)

        if self._is_dragging_free_select and self._free_select_points and len(self._free_select_points) >= 2:
            free_select_pen = QtGui.QPen(QtGui.QColor(0, 255, 255, 255), 2 / self.scale)
            free_select_brush = QtGui.QBrush(QtGui.QColor(0, 255, 255, 50))
            p.setPen(free_select_pen)
            p.setBrush(free_select_brush)
            q_polygon = QtGui.QPolygonF()
            for pt in self._free_select_points:
                q_polygon.append(QtCore.QPointF(pt[0], pt[1]))
            p.drawPolygon(q_polygon)

        if (
            self._crosshair.get(self._createMode, False)
            and self.drawing()
            and self.prevMovePoint
            and not self.outOfPixmap(self.prevMovePoint)
        ):
            p.setPen(QtGui.QColor(0, 0, 0))
            p.drawLine(
                0,
                int(self.prevMovePoint.y()),
                self.width() - 1,
                int(self.prevMovePoint.y()),
            )
            p.drawLine(
                int(self.prevMovePoint.x()),
                0,
                int(self.prevMovePoint.x()),
                self.height() - 1,
            )

        Shape.scale = self.scale
        MultipoinstShape.scale = self.scale
        for shape in self.shapes:
            if (shape.selected or not self._hideBackround) and self.isVisible(
                shape
            ):
                shape.fill = shape.selected or shape == self.hShape
                shape.paint(p)
        
        if self._selected_vertices:
            vertex_pen = QtGui.QPen(QtGui.QColor(0, 255, 0, 200), 2 / self.scale)
            vertex_brush = QtGui.QBrush(QtGui.QColor(0, 255, 0, 200))
            p.setPen(vertex_pen)
            p.setBrush(vertex_brush)
            for shape, idx in self._selected_vertices:
                point = shape.points[idx]
                radius = 5 / self.scale
                p.drawEllipse(point, radius, radius)

        if self.current:
            self.current.paint(p)
            self.line.paint(p)

        if self.selectedShapesCopy:
            for s in self.selectedShapesCopy:
                s.paint(p)

        if (
            self.fillDrawing()
            and self.createMode == "polygon"
            and self.current is not None
            and len(self.current.points) >= 2
        ):
            drawing_shape = self.current.copy()
            drawing_shape.addPoint(self.line[1])
            drawing_shape.fill = True
            drawing_shape.paint(p)
        p.end()

    def transformPos(self, point):
        pos = point / self.scale - self.offsetToCenter()
        if not self.pixmap.isNull():
            w = self.pixmap.width() - 1
            h = self.pixmap.height() - 1
            # 强制所有点击限制在图片内，空白区点击=贴边
            pos.setX(max(0.0, min(pos.x(), w)))
            pos.setY(max(0.0, min(pos.y(), h)))
        return pos

    def offsetToCenter(self):
        # ✅ LabelMe 5.9.1 官方原版：四周永久空白 + 滚动条完美兼容
        if self.pixmap.isNull():
            return QtCore.QPointF(0, 0)
        
        s = self.scale
        # 图片缩放后的实际尺寸
        img_w = self.pixmap.width() * s
        img_h = self.pixmap.height() * s
        # 画布窗口的实际尺寸
        win_w = self.width()
        win_h = self.height()

        # 核心：水平居中 + 最小左边距=空白大小
        x_offset = (win_w - img_w) / 2
        x_offset = max(x_offset, self.CANVAS_PADDING)
        # 核心：垂直居中 + 最小上边距=空白大小
        y_offset = (win_h - img_h) / 2
        y_offset = max(y_offset, self.CANVAS_PADDING)

        # 转换为缩放后的坐标
        return QtCore.QPointF(x_offset / s, y_offset / s)

    def outOfPixmap(self, p):
        w, h = self.pixmap.width(), self.pixmap.height()
        return not (0 <= p.x() <= w - 1 and 0 <= p.y() <= h - 1)

    def closeEnough(self, p1, p2):
        return labelme.utils.distance(p1 - p2) < (self.epsilon / self.scale)

    def intersectionPoint(self, p1, p2):
        size = self.pixmap.size()
        points = [
            (0, 0),
            (size.width() - 1, 0),
            (size.width() - 1, size.height() - 1),
            (0, size.height() - 1),
        ]
        x1 = min(max(p1.x(), 0), size.width() - 1)
        y1 = min(max(p1.y(), 0), size.height() - 1)
        x2, y2 = p2.x(), p2.y()
        intersections = list(self.intersectingEdges((x1, y1), (x2, y2), points))
        if not intersections:
            return QtCore.QPointF(x1, y1)
        d, i, (x, y) = min(intersections)
        x3, y3 = points[i]
        x4, y4 = points[(i + 1) % 4]
        if (x, y) == (x1, y1):
            if x3 == x4:
                return QtCore.QPointF(x3, min(max(0, y2), max(y3, y4)))
            else:
                return QtCore.QPointF(min(max(0, x2), max(x3, x4)), y3)
        return QtCore.QPointF(x, y)

    def intersectingEdges(self, point1, point2, points):
        (x1, y1) = point1
        (x2, y2) = point2
        for i in range(4):
            x3, y3 = points[i]
            x4, y4 = points[(i + 1) % 4]
            denom = (y4 - y3) * (x2 - x1) - (x4 - x3) * (y2 - y1)
            nua = (x4 - x3) * (y1 - y3) - (y4 - y3) * (x1 - x3)
            nub = (x2 - x1) * (y1 - y3) - (y2 - y1) * (x1 - x3)
            if denom == 0:
                continue
            ua, ub = nua / denom, nub / denom
            if 0 <= ua <= 1 and 0 <= ub <= 1:
                x = x1 + ua * (x2 - x1)
                y = y1 + ua * (y2 - y1)
                m = QtCore.QPointF((x3 + x4) / 2, (y3 + y4) / 2)
                d = labelme.utils.distance(m - QtCore.QPointF(x2, y2))
                yield d, i, (x, y)

    def sizeHint(self):
        return self.minimumSizeHint()

    def minimumSizeHint(self):
        if self.pixmap.isNull():
            return super(Canvas, self).minimumSizeHint()
        # 关键：右侧、下侧额外增加空白区域，让滚动条包含空白
        w = self.pixmap.width() * self.scale + 2 * self.CANVAS_PADDING
        h = self.pixmap.height() * self.scale + 2 * self.CANVAS_PADDING
        return QtCore.QSize(int(w), int(h))

    def wheelEvent(self, ev):
        if QT5:
            mods = ev.modifiers()
            delta = ev.angleDelta()
            delta_y = delta.y()
            delta_x = delta.x()
        else:
            delta_y = ev.delta() if ev.orientation() == QtCore.Qt.Vertical else 0
            delta_x = ev.delta() if ev.orientation() == QtCore.Qt.Horizontal else 0
            mods = ev.modifiers()
        
        if QtCore.Qt.ControlModifier == int(mods):
            self.zoomRequest.emit(delta_y, ev.pos())
        else:
            horizontal_delta = int(delta_x * WHEEL_SCROLL_SPEED)
            self.scrollRequest.emit(horizontal_delta, QtCore.Qt.Horizontal)
            vertical_delta = int(delta_y * WHEEL_SCROLL_SPEED)
            self.scrollRequest.emit(vertical_delta, QtCore.Qt.Vertical)
        ev.accept()

    def moveByKeyboard(self, offset):
        scaled_speed = MOVE_SPEED / self.scale
        offset = QtCore.QPointF(offset.x() * scaled_speed, offset.y() * scaled_speed)
        if self.selectedShapes:
            self.boundedMoveShapes(
                self.selectedShapes, self.prevPoint + offset
            )
            self.repaint()
            self.movingShape = True

    def keyReleaseEvent(self, ev):
        key = ev.key()
        if key == QtCore.Qt.Key_S and self.drawing():
            self._create_snap_enabled = False
        modifiers = ev.modifiers()
        if self.drawing():
            if int(modifiers) == 0:
                self.snapping = True
        elif self.editing():
            if self.movingShape and self.selectedShapes:
                valid_selected = [s for s in self.selectedShapes if s in self.shapes]
                if not valid_selected:
                    self.selectedShapes = []
                    self.movingShape = False
                    return
                self.selectedShapes = valid_selected

                index = self.shapes.index(self.selectedShapes[0])
                if (
                        self.shapesBackups[-1][index].points
                        != self.shapes[index].points
                ):
                    self.storeShapes()
                    self.shapeMoved.emit()

                self.movingShape = False

    def undoLastLine(self):
        if not self.shapes:
            return
        self.current = self.shapes.pop()
        if self.current in self.selectedShapes:
            self.selectedShapes.remove(self.current)
        if not isinstance(self.current, MaskShape) and hasattr(self.current, 'setOpen'):
            self.current.setOpen()
        if self.createMode in ["polygon", "linestrip"]:
            self.line.points = [self.current[-1], self.current[0]] if len(self.current) >= 1 else []
        elif self.createMode in ["rectangle", "line", "circle"]:
            self.current.points = self.current.points[:1] if self.current.points else []
        elif self.createMode in ["point", "polygonSAM", "rectangleSAM"]:
            self.current = None
        self.drawingPolygon.emit(True)

    def undoLastPoint(self):
        if not self.current or self.current.isClosed():
            return
        self.current.popPoint()
        if len(self.current) > 0:
            self.line[0] = self.current[-1]
        else:
            self.current = None
            self.drawingPolygon.emit(False)
        self.update()

    def loadPixmap(self, pixmap, clear_shapes=True):
        self.selectedShapes = []
        self.hShape = None
        self.hVertex = None
        self.prevhVertex = None
        self.vertexSelected.emit(False)
        self.selectionChanged.emit([])

        self.pixmap = pixmap
        if clear_shapes:
            self.shapes = []
            self.sam_mask = MaskShape()
            self.current = None
            self.selectedShapesCopy = []
            self.unHighlight()
            self.shapesBackups = []
        if (self.createMode == "polygonSAM" or self.createMode == "rectangleSAM") and self.pixmap and self.sam_predictor:
            self.samEmbedding()
        self.update()

    def loadShapes(self, shapes, replace=True):
        if replace:
            self.shapes = list(shapes)
        else:
            self.shapes.extend(shapes)
        self.storeShapes()
        self.current = None
        self.sam_mask = MaskShape()
        self.hShape = None
        self.hVertex = None
        self.hEdge = None
        self.update()

    def setShapeVisible(self, shape, value):
        self.visible[shape] = value
        self.update()

    def overrideCursor(self, cursor):
        self.restoreCursor()
        self._cursor = cursor
        QtWidgets.QApplication.setOverrideCursor(cursor)

    def restoreCursor(self):
        QtWidgets.QApplication.restoreOverrideCursor()

    def resetState(self):
        self.restoreCursor()
        self.pixmap = None
        self.shapesBackups = []
        self.update()

# 权重下载地址见 labelme/sam_weight.py（MIRRORS）
