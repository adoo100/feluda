import os, sys, json, datetime, copy, uuid, requests
from dotenv import load_dotenv
load_dotenv()
import logging
from flask import Flask, request, jsonify 
from flask_cors import CORS
from pymongo import MongoClient
from io import BytesIO
import skimage, PIL
import numpy as np
from monitor import timeit
from elasticsearch import Elasticsearch
from elasticsearch import helpers as eshelpers
from VideoAnalyzer import VideoAnalyzer, compress_video
from analyzer import ResNet18, detect_text, image_from_url, doc2vec, detect_lang
from search import ImageSearch, TextSearch, DocSearch
from helper import index_data
# from send import add_job_to_queue
import cv2
from indices import check_index
from datetime import datetime
import wget

imagesearch = ImageSearch()
docsearch = DocSearch()
textsearch = TextSearch()
resnet18 = ResNet18()

application = Flask(__name__)
CORS(application)

logger = logging.getLogger("tattle-api")

mongo_url = os.environ['MONGO_URL']
cli = MongoClient(mongo_url)
db = cli[os.environ.get("DB_NAME")]
coll = db[os.environ.get("DB_COLLECTION")]

es_host = os.environ['ES_HOST']
es_vid_index = os.environ['ES_VID_INDEX']
es_img_index = os.environ['ES_IMG_INDEX']
es_txt_index = os.environ['ES_TXT_INDEX']

# Create ES indices if they don't exist
config = {'host': es_host}
es = Elasticsearch([config,])
check_index(es, es_vid_index, index_type="video")
# check_index(es, es_img_index, index_type="image")
check_index(es, es_txt_index, index_type="text")

@application.route('/health')
def health_check():
    logger.debug('<health-check>')
    return "OK"

@application.route('/media', methods=['POST'])
def media():
    try:
        data = request.get_json(force=True)
        print(data)
        print("Adding requested job to indexing queue ...")
        add_job_to_queue(data)
        print("Job added")
        return 'media enqueued', 200
    except Exception as e:
        return 'Error indexing media : '+str(e), 500


@timeit
@application.route('/search', methods=['POST'])
def search():
    data = request.get_json(force=True)

    def query_es(index, vec):
        if type(vec) == np.ndarray:
            vec = vec.tolist()
        if index == es_txt_index:
            calculation = "1 / (1 + l2norm(params.query_vector, 'text_vec'))"
        else:
            calculation = None

        q = {
        "size": 10,
            "query": {
                "script_score": {
                    "query" : {
                        "match_all" : {}
                        },
                    "script": {
                        "source": calculation, 
                        "params": {"query_vector": vec}
                        }
                    }
                }
            }
            
        resp = es.search(index=index, body = q)

        # For simple text search
        # resp = es.search(
        #     index=index, 
        #     body = {"query": {
        #                 "match": {
        #                     "text": data["text"]}}})

        doc_ids, dists, source_ids, sources, texts = [], [], [], [], [] 

        for h in resp['hits']['hits']:
            doc_ids.append(h['_id'])
            dists.append(h['_score'])
            source_ids.append(h["_source"]["source_id"])
            sources.append(h["_source"]["source"])
            texts.append(h["_source"]["text"])

        return doc_ids, dists, source_ids, sources, texts # for development only. return only required info in production

    if data["media_type"] == "text": # add error handling
        text = data["text"]
        lang = detect_lang(text)
        print("Generating document vector")
        query_vec = doc2vec(text)
        print("Document vector generated")
        doc_ids, dists, source_ids, sources, texts = query_es(index=es_txt_index, vec=query_vec)
        return jsonify(doc_ids, dists, source_ids, sources, texts)

    # text = data.get('text', None)
    # thresh = data.get('threshold') # What is thresh?
    # sources = data.get('source', [])
    # image_url = data.get('image_url', None)
    # es_flag = data.get('es_flag', 0)
    # if text is None and image_url is None:
    #     ret = {'failed' : 1, 'error' : 'No text or image_url found'}

    # elif image_url is not None:
    #     image_dict = image_from_url(image_url)
    #     image = image_dict['image']
    #     image = image.convert('RGB') #take care of png(RGBA) issue
    #     vec = resnet18.extract_feature(image)

    #     if int(es_flag) == 1:
    #         doc_ids, dists = query_es(vec)
    #     elif thresh:
    #         doc_ids, dists = imagesearch.search(vec, thresh)
    #     else:
    #         doc_ids, dists = imagesearch.search(vec)

    #     # only get first 10
    #     # doc_ids, dists = doc_ids[:10], dists[:10]

    #     sources = {d.get('doc_id') : d.get('source') for d in coll.find({"doc_id" : {"$in" : doc_ids}})}

    #     if doc_ids is not None:
    #         # result = [{'doc_id' : doc_ids[i], 'dist' : dists[i], 'source' : sources.get(doc_ids[i], None)} for i in range(min(10, len(doc_ids)))]
    #         result = [{'doc_id' : doc_ids[i], 'dist' : dists[i], 'source' : sources.get(doc_ids[i], None)} for i in range(len(doc_ids))]
    #         ret = {'failed' : 0, 'result' : result}
    #     else:
    #         ret = {'failed' : 0, 'result' : []}

    # elif text is not None:
    #     duplicate_doc = coll.find_one({"text" : text})
    #     vec = doc2vec(text)
    #     if vec is None:
    #         ret = {'failed' : 1, 'error' : 'query words not found in db'}
    #     doc_ids, dists = textsearch.search(vec)
    #     sources = {d.get('doc_id') : d.get('source') for d in coll.find({"doc_id" : {"$in" : doc_ids}})}
    #     if doc_ids is not None:
    #         # result = [{'doc_id' : doc_ids[i], 'dist' : dists[i], 'source' : sources[doc_ids[i]]} for i in range(min(10,len(doc_ids)))]
    #         result = [{'doc_id' : doc_ids[i], 'dist' : dists[i], 'source' : sources[doc_ids[i]]} for i in range(len(doc_ids))]
    #     else:
    #         result = []

    #     if duplicate_doc is not None:
    #         result = [{'doc_id' : duplicate_doc.get('doc_id') , 'dist' : 0.0, 'source' : duplicate_doc.get('source')}] + result

    #     ret = {'failed' : 0, 'duplicate' : 1, 'result' : result}

    # else:
    #     ret = {'failed' : 1, 'error' : 'something went wrong'}

    # return jsonify(ret)

@application.route('/find_text', methods=['POST'])
def find_text():
    data = request.get_json(force=True)
    image_url = data.get('image_url')
    image_dict = image_from_url(image_url)
    return jsonify(detect_text(image_dict['image_bytes']))

@application.route('/delete_doc', methods=['POST'])
def delete_doc():
    data = request.get_json(force=True)
    doc_id = data.get('source_id')
    ret = {}
    if not doc_id:
        ret['failed'] = 1
        ret['error'] = 'no doc id provided'
        return jsonify(ret)

    result = coll.delete_one({"doc_id" : doc_id})
    if result.deleted_count == 1:
        ret['failed'] = 0
    else:
        ret['failed'] = 1
        ret['error'] = 'no matching document'
    return jsonify(ret)

@application.route('/search_tags', methods=['POST'])
def search_tags():
    ret = {}
    data = request.get_json(force=True)
    tags = data.get('tags')
    if not tags:
        ret['failed'] = 1
        ret['error'] = 'no tags provided'
        return jsonify(ret)

    sources = data.get('sources')
    if sources:
        query = {"tags.value" : {"$in" : tags}, "tags.source" : {"$in" : sources}}
    else:
        query = {"tags.value" : {"$in" : tags}}

    docs = []
    for doc in coll.find(query):
        docs.append(doc.get('doc_id'))

    ret['docs'] = docs
    ret['failed'] = 0
    return jsonify(ret)

@application.route('/update_tags', methods=['POST'])
def update_tags():
    """
    tags are stored as follows:
    'tags' : [{'value' : 'politics' , 'source' : 'tattle'},
              {'value' : 'election' , 'source' : 'TOI'   },
              {'value' : 'politics' , 'source' : 'altnews'}]

    update_tags will only have a list of tags ['election','politics'] and a source : 'tattle'
    it'll create two tags: [{'value' : 'election' , 'source' : 'tattle'}, {'value' : 'politics', 'source' : 'tattle'}]
    """
    data = request.get_json(force=True)
    doc_id = data.get('doc_id')
    tags = data.get('tags') # e.g. [{'tag' : 'politics', 'source' : 'tattle'}, {'tag' : 'election', 'source' : 'TOI'}
    source = data.get('source') or 'tattle'
    if doc_id is None:
        ret = {'failed' : 1, 'error' : 'no doc_id provided'}
    elif tags is None:
        ret = {'failed' : 1, 'error' : 'no tags provided'}
    else:
        doc = coll.find_one({"doc_id" : doc_id})
        if doc is None:
            ret = {'failed' : 1, 'error' : 'doc not found'}
        else:
            new_tags = [{'value' : t, 'source':source} for t in tags]
            all_tags = new_tags + doc.get('tags', [])
            updated_tags = list({(t['value'],t['source']):t for t in all_tags}.values())

            date = datetime.datetime.now()
            coll.update_one({"doc_id" : doc_id}, {"$set" : 
                {"tags" : updated_tags, "date_updated" : date}})
            ret = {'failed' : 0}
    return jsonify(ret)

@application.route('/remove_tags', methods=['POST'])
def remove_tags():
    data = request.get_json(force=True)
    doc_id = data.get('doc_id')
    tags = data.get('tags')
    source = data.get('source')
    if doc_id is None:
        ret = {'failed' : 1, 'error' : 'no doc_id provided'}
    elif tags is None:
        ret = {'failed' : 1, 'error' : 'no tags provided'}
    elif source is None:
        ret = {'failed' : 1, 'error' : 'no source provided'}
    else:
        doc = coll.find_one({"doc_id" : doc_id})
        if doc is None:
            ret = {'failed' : 1, 'error' : 'doc not found'}
        else:
            to_remove_tags = [{'value' : t, 'source':source} for t in tags]
            updated_tags = doc.get('tags',[])
            removed = []
            for tag in to_remove_tags:
                if tag in updated_tags:
                    updated_tags.remove(tag)
                    removed.append(tag)
            date = datetime.datetime.now()
            coll.update_one({"doc_id" : doc_id}, {"$set" : 
                {"tags" : updated_tags, "date_updated" : date}})
            ret = {'failed' : 0, 'removed_tags':removed}
    return jsonify(ret)

def analyze_image(image_url):
    image = skimage.io.imread(image_url)
    image = PIL.Image.fromarray(image)
    embedding = get_image_embedding(image)

@application.route('/upload_text', methods=['POST'])
def upload_text():
    print(request.get_data())
    data = request.get_json(force=True)
    res = index_data(es, data)
    return jsonify(res)

@application.route('/upload_video', methods=['POST'])
def upload_video():
    print(request.get_data())
    data = request.get_json(force=True)
    res = index_data(es, data)
    return jsonify(res)

@application.route('/upload_image', methods=['POST'])
def upload_image():
    print(request.get_data())
    data = request.get_json(force=True)
    res = index_data(es, data)
    return(jsonify(res))
 
if __name__ == "__main__":
    application.run(host="0.0.0.0", port=7000, debug=True)
