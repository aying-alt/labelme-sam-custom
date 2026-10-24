> **示例图片未随本仓库分发。** 本文档中的图片链接指向原图，本仓库出于第三方数据集授权考虑已移除。
> 需要查看效果请前往 [上游仓库](https://github.com/fry404006308/labelme-with-segment-anything)，或直接用自己的图片。

# Semantic Segmentation Example

## Annotation

```bash
labelme data_annotated --labels labels.txt --nodata --validatelabel exact --config '{shift_auto_shape_color: -2}'
```

![](.readme/annotation.jpg)


## Convert to VOC-format Dataset

```bash
# It generates:
#   - data_dataset_voc/JPEGImages
#   - data_dataset_voc/SegmentationClass
#   - data_dataset_voc/SegmentationClassVisualization
./labelme2voc.py data_annotated data_dataset_voc --labels labels.txt
```

<img src="data_dataset_voc/JPEGImages/2011_000003.jpg" width="33%" /> <img src="data_dataset_voc/SegmentationClassPNG/2011_000003.png" width="33%" /> <img src="data_dataset_voc/SegmentationClassVisualization/2011_000003.jpg" width="33%" />

Fig 1. JPEG image (left), PNG label (center), JPEG label visualization (right)  


Note that the label file contains only very low label values (ex. `0, 4, 14`), and
`255` indicates the `__ignore__` label value (`-1` in the npy file).  
You can see the label PNG file by following.

```bash
labelme_draw_label_png data_dataset_voc/SegmentationClassPNG/2011_000003.png
```

<img src=".readme/draw_label_png.jpg" width="33%" />
