## Use Cases 

### Research Paper Summarization
Research papers can be summarized to enable researchers spend less time on selecting papers to be read among a list of papers. You can directly infer with an already existing extractive summarization model on the Hugging Face Hub and get the summaries of each paper. You can also take a model like BERT from the Hugging Face Hub and fine-tune on biomedical text and then further fine-tune on summarization task. You can also use sequence-to-sequence models like T5 for abstractive text summarization.

## Inference
You can use “summarization” pipeline to infer with the summarization models. Summarization pipeline returns a json with the summarized text. If no model name is provided, pipeline will be initialized with [sshleifer/distilbart-cnn-12-6](https://huggingface.co/sshleifer/distilbart-cnn-12-6).

```python
from transformers import pipeline

classifier = pipeline("summarization")
classifier("Paris is the capital and most populous city of France, with an estimated population of 2,175,601 residents as of 2018, in an area of more than 105 square kilometres (41 square miles). The City of Paris is the centre and seat of government of the region and province of Île-de-France, or Paris Region, which has an estimated population of 12,174,880, or about 18 percent of the population of France as of 2017.”)
## [{ "summary_text": " Paris is the capital and most populous city of France, with an estimated 
# population of 2,175,601 residents as of 2018 . The city is the centre and seat of government of the region 
# and province of Île-de-France, or Paris Region . Paris Region has an estimated 18 percent 
# of the population of France as of 2017 ." }]
```

## Useful Resources
- [Course Chapter on Summarization](https://huggingface.co/course/chapter7/5?fw=pt)

### Notebooks on Summarization
- [PyTorch](https://github.com/huggingface/notebooks/blob/master/examples/summarization.ipynb)
- [TensorFlow](https://github.com/huggingface/notebooks/blob/master/examples/summarization-tf.ipynb)

### Scripts for Summarization
- [PyTorch](https://github.com/huggingface/notebooks/blob/master/examples/summarization.ipynb)
- [TensorFlow](https://github.com/huggingface/notebooks/blob/master/examples/summarization-tf.ipynb)
- [Flax](https://github.com/huggingface/transformers/tree/master/examples/flax/summarization)

### Blog Posts on Summarization
-[Distributed Training: Train BART/T5 for Summarization using 🤗 Transformers and Amazon SageMaker](https://huggingface.co/blog/sagemaker-distributed-training-seq2seq)