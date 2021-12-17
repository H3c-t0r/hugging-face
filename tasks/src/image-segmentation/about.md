## Use Cases

### Autonomous Driving
Segmentation models are used to identify road patterns such as lanes and obstacles for safer drive. 

### Background Removal 
Image segmentation models are used in cameras to erase background of certain objects and apply filters on them. 

### Medical Imaging
Image segmentation models are used to distinguish organs or tissues, which improves the workflows in medical imaging. The models are used to segment the dental instances, analyze X-Ray scans or even segment cells for pathological diagnosis. This [dataset]([https://github.com/v7labs/covid-19-xray-dataset](https://github.com/v7labs/covid-19-xray-dataset)) contains images of lungs of healthy patients and patients with COVID-19 segmented with masks. Another [segmentation dataset]([https://ivdm3seg.weebly.com/data.html](https://ivdm3seg.weebly.com/data.html)) contains segmented MRI data of lower spine to analyze the effect of spaceflight simulation.

## Task Variants

### Semantic Segmentation 
Semantic segmentation is the task of segmenting parts of an image together which belong to the same class. Semantic segmentation models make predictions for each pixel and return the probabilities of classes for each pixel. These models are evaluated on Mean Intersection Over Union (Mean IoU).

### Instance Segmentation
Instance segmentation is the variant of image segmentation where every distinct object is segmented, instead of one segment per class. 

### Panoptic Segmentation
Panoptic Segmentation is the image segmentation task that segments the image both instance-wise and class-wise, it has assigns every pixel a distinct instance of the class.

## Inference
You can infer with the image segmentation models using image-segmentation pipeline, to use the  pipeline, you need to install [timm](https://github.com/rwightman/pytorch-image-models) first. 

```python
!pip install timm
model = pipeline("image-segmentation")
model("cat.png")
#[{'label': 'cat',
#  'mask': mask_code,
#  'score': 0.999}
# ...]
```

