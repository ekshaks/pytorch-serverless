try:
	import unzip_requirements
except ImportError:
	pass

import os, json, traceback
import urllib.parse
import torch
import numpy as np

from lib.models import classification_model
from lib.utils import download_file, get_labels, open_image_url
from fastai.core import A, T, VV_
from fastai.transforms import tfms_from_stats


BUCKET_NAME = os.environ['BUCKET_NAME']
STATE_DICT_NAME = os.environ['STATE_DICT_NAME']
STATS = A(*eval(os.environ['IMAGE_STATS']))
SZ = int(os.environ['IMAGE_SIZE'])
LABELS_PATH = os.environ['LABELS_PATH']

class SetupModel(object):
	model = classification_model()
	labels = get_labels(LABELS_PATH)
	tfms = tfms_from_stats(STATS, SZ)[-1]

	def __init__(self, f):
		self.f = f
		file_path = f'/tmp/{STATE_DICT_NAME}'
		download_file(BUCKET_NAME, STATE_DICT_NAME, file_path)
		state_dict = torch.load(file_path, map_location=lambda storage, loc: storage)
		self.model.load_state_dict(state_dict), self.model.eval()
		os.remove(file_path)

	def __call__(self, *args, **kwargs):
		return self.f(*args, **kwargs)


def build_pred(label_idx, log, prob):
	label = SetupModel.labels[label_idx]
	return dict(label=label, log=float(log), prob=float(prob))


def parse_params(params):
	image_url = urllib.parse.unquote_plus(params.get('image_url', ''))
	n_labels = len(SetupModel.labels)
	top_k = int(params.get('top_k', 3))
	if top_k < 1: top_k = n_labels
	return dict(image_url=image_url, top_k=min(top_k, n_labels))


def predict(img):
	batch = [T(SetupModel.tfms(img))]
	inp = VV_(torch.stack(batch))
	return SetupModel.model(inp)


@SetupModel
def handler(event, _):
	if event is None: event = {}
	print(event)
	try:
		# keep the lambda function warm
		if event.get('detail-type') == 'Scheduled Event':
			return 'nice & warm'

		params = parse_params(event.get('queryStringParameters', {}))

		out = predict(open_image_url(params['image_url']))
		top = out.topk(params.get('top_k'), sorted=True)

		logs, idxs = (t.data.numpy()[-1] for t in top)
		probs = np.exp(logs)
		preds = [build_pred(idx, logs[i], probs[i]) for i, idx in enumerate(idxs)]

		response_body = dict(predictions=preds)
		response = dict(statusCode=200, body=response_body)

	except Exception as e:
		response_body = dict(error=str(e), traceback=traceback.format_exc())
		response = dict(statusCode=500, body=response_body)

	response['body'] = json.dumps(response['body'])
	print(response)
	return response