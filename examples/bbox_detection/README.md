> **示例图片未随本仓库分发。** 本文档中的图片链接指向原图，本仓库出于第三方数据集授权考虑已移除。
> 需要查看效果请前往 [上游仓库](https://github.com/fry404006308/labelme-with-segment-anything)，或直接用自己的图片。

# Bounding Box Detection Example


## Usage

```bash
labelme data_annotated --labels labels.txt --nodata --autosave
```

![](.readme/annotation.jpg)


## Convert to VOC-format Dataset

```bash
# It generates:
#   - data_dataset_voc/JPEGImages
#   - data_dataset_voc/Annotations
#   - data_dataset_voc/AnnotationsVisualization
./labelme2voc.py data_annotated data_dataset_voc --labels labels.txt
```

<img src="data_dataset_voc/JPEGImages/2011_000003.jpg" width="33%" /> <img src="data_dataset_voc/AnnotationsVisualization/2011_000003.jpg" width="33%" />

<i>Fig1. JPEG image (left), Bounding box annotation visualization (right).</i>
