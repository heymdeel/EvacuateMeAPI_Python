from flask import Blueprint, request, jsonify
from models import *
from google_maps import make_request_to_google, get_distance, get_duration
from datetime import datetime

order_api = Blueprint('order_api', __name__)


@order_api.route('/api/help/companies', methods=['POST']) #get list of companies for client
@db_session
def list_of_companies():
    if 'api_key' not in request.headers:
        return 'Access refused! Need authorization via api_key', 401

    api_key = request.headers['api_key']
    if not Clients.exists(lambda c: c.api_key == api_key):
        return 'Access refused! api_key is wrong', 401

    req_json = request.get_json()
    client_lat = req_json['latitude']
    client_long = req_json['longitude']
    client_car_type = req_json['car_type']

    companies = []
    for worker in Workers.select(lambda w: w.status.id == 1 and w.supported_car_type.id == client_car_type): #find matching workers
        worker_location = Workers_last_location.get(worker=worker)
        result = make_request_to_google(client_lat, client_long, worker_location.latitude, worker_location.longitude)
        distance = get_distance(result)
        duration = get_duration(result)

        company_in_list = False
        for c in companies:
            if c['id'] == worker.company.id: #if company is already in list check for new minimal distance
                if distance < c['closest_distance']:
                    c['closest_distance'] = distance
                    c['closest_duration'] = duration
                company_in_list = True
                break

        if not company_in_list: #add new company to list
            company = worker.company.to_dict(exclude=['login', 'password', 'api_key', 'sum_rate', 'count_rate'])

            if worker.company.count_rate != 0:
                company['rate'] = worker.company.sum_rate / worker.company.count_rate
            else:
                company['rate'] = 0

            company['closest_distance'] = distance
            company['closest_duration'] = duration
            company['closest_worker_id'] = worker.id
            companies.append(company)

    if not companies:
        return '', 404

    companies.sort(key=lambda x: x['closest_distance'])
    return jsonify(companies), 200


@order_api.route('/api/orders', methods=['POST']) #add order to the database
@db_session
def create_order():
    if 'api_key' not in request.headers:
        return 'Access refused! Need authorization via api_key', 401

    api_key = request.headers['api_key']
    if not Clients.exists(lambda c: c.api_key == api_key):
        return 'Access refused! api_key is wrong', 401

    req_json = request.get_json()
    client_lat = req_json['latitude']
    client_long = req_json['longitude']
    client_car_type = req_json['car_type']
    company = Companies.get(id=req_json['company_id'])
    worker = Workers.get(id=req_json['worker_id'])
    commentary = req_json['commentary']

    if worker not in company.workers:
        return '', 400

    if worker.status.id != 1:
        return 'worker is busy', 404

    worker_location = Workers_last_location.get(worker=worker)
    order = Orders(client=Clients.get(api_key=api_key), worker=worker, start_client_lat=client_lat,
                   start_client_long=client_long, start_worker_lat=worker_location.latitude,
                   start_worker_long=worker_location.longitude, beginning_time=datetime.now(),
                   car_type=client_car_type, status=0, commentary=commentary)
    commit()

    response = {}
    response['oder_id'] = order.id
    response['name'] = worker.name
    response['surname'] = worker.surname
    response['latitude'] = worker_location.latitude
    response['longitude'] = worker_location.longitude
    response['phone'] = worker.phone

    return jsonify(response), 201


@order_api.route('/api/orders/<int:order_id>/status/<int:new_status>', methods=['PUT']) #change order status
@db_session
def change_order_status(order_id, new_status):
    if 'api_key' not in request.headers:
        return 'Access refused! Need authorization via api_key', 401

    order = Orders.get(id=order_id)
    if order is None:
        return 'There is no order with such id', 404

    api_key = request.headers['api_key']

    user = Clients.get(api_key=api_key)
    if user is not None:
        if order.client != user:
            return 'Bad user', 400

        if order.status.id in [0, 1] and new_status == 5:
            order.status = new_status
            return 'status successfully changed to canceled by user', 200

        return 'bad status', 400

    user = Workers.get(api_key=api_key)
    if user is not None:
        if order.worker != user:
            return 'Bad worker', 400

        if (order.status.id == 0 and new_status in [1, 4]) or (order.status.id == 1 and new_status in [2, 4]) \
                or (order.status.id == 2 and new_status == 3):
            order.status = new_status
            return 'status successfully changed to ' + Orders_status.get(id=new_status).description, 200

        return 'bad status', 400

    return 'Refused! wrong api_key', 401
