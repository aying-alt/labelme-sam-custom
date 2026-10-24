> **示例图片未随本仓库分发。** 本文档中的图片链接指向原图，本仓库出于第三方数据集授权考虑已移除。
> 需要查看效果请前往 [上游仓库](https://github.com/fry404006308/labelme-with-segment-anything)，或直接用自己的图片。

# Video Annotation Example


## Annotation

```bash
labelme data_annotated --labels labels.txt --nodata --keep-prev --config '{shift_auto_shape_color: -2}'
```

<img src=".readme/00000100.jpg" width="49%" /> <img src=".readme/00000101.jpg" width="49%" />

*Fig 1. Video annotation example. A frame (left), The next frame (right).*


<img src=".readme/data_annotated.gif" width="98%" />

*Fig 2. Visualization of video semantic segmentation.*


## How to Convert a Video File to Images for Annotation?

```bash
pip install video-cli

video-toimg your_video.mp4  # this creates your_video/ directory
ls your_video/

labelme your_video/
```
