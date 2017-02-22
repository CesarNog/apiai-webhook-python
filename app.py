#!/usr/bin/env python

from __future__ import print_function

import logging
import os
from _decimal import Decimal

import requests
from future.standard_library import install_aliases
from wikipedia import wikipedia

install_aliases()

from urllib.parse import urlencode
from urllib.request import urlopen

import json

from flask import Flask
from flask import request
from flask import make_response

# Flask app should start in global layout
app = Flask(__name__)

logger = logging.getLogger(__name__)


@app.route('/webhook', methods=['POST'])
def webhook():
    req = request.get_json(silent=True, force=True)

    print("Request:")
    print(json.dumps(req, indent=4))

    res = process_request(req)

    res = json.dumps(res, indent=4)
    # print(res)
    r = make_response(res)
    r.headers['Content-Type'] = 'application/json'
    return r


def process_request(req):
    action = req.get("result").get("action")

    if action != "yahooWeatherForecast":
        if action == u"weather.search":
            try:
                parameters = req.get("result").get("parameters")
                request_type = parameters.get('request_type')
                current_time = parameters.get('current_time')
                location = parameters.get('location')

                return weather_request_hangouts(None, None, location)
            except Exception as e:
                return {}
                # Do something else
        if u"wisdom" in action:
            parameters = req.get("result").get("parameters")
            query_wisdom = parameters.get('q')
            request_type = parameters.get('request_type')

            try:
                wikipedia_answer_url = None
                wisdom_answer = None
                speech = None
                if query_wisdom:
                    wikipedia_search = wikipedia.search(query_wisdom, results=2)[0]
                    wikipedia_answer_url = wikipedia.page(wikipedia_search).url
                    if wikipedia_answer_url:
                        wisdom_answer = wikipedia.summary(query_wisdom, sentences=1)
                    else:
                        wikipedia_search = wikipedia.search(query_wisdom, results=2)[1]
                        wikipedia_answer_url = wikipedia.page(wikipedia_search).url

                    if wisdom_answer and wikipedia_answer_url:
                        speech = "According to Wikipedia.org (" + wikipedia_answer_url + "): " + wisdom_answer
                    else:
                        speech = "I am sorry, but I couldn't find a good article or result for your " \
                                 "request on Wikipedia.org " \
                                 "Why don't you click on the following link to see similar results: "
                        "https://en.wikipedia.org/w/index.php?search=" + wisdom_answer.replace(" ", "+")

                    return {
                        "speech": speech,
                        "displayText": speech,
                        # "data": data,
                        # "contextOut": [],
                        "source": "apiai-weather-webhook-sample"
                    }
            except Exception as e:
                logger.error("Error")

        return {}

    baseurl = "https://query.yahooapis.com/v1/public/yql?"
    yql_query = make_yql_query(req)
    if yql_query is None:
        return {}
    yql_url = baseurl + urlencode({'q': yql_query}) + "&format=json"
    result = urlopen(yql_url).read()
    data = json.loads(result)
    res = make_webhook_result(data)
    return res


def make_yql_query(req):
    result = req.get("result")
    parameters = result.get("parameters")
    city = parameters.get("geo-city")
    if city is None:
        return None

    return "select * from weather.forecast where woeid in (select woeid from geo.places(1) where text='" + city + "')"


def make_webhook_result(data):
    query = data.get('query')
    if query is None:
        return {}

    result = query.get('results')
    if result is None:
        return {}

    channel = result.get('channel')
    if channel is None:
        return {}

    item = channel.get('item')
    location = channel.get('location')
    units = channel.get('units')
    if (location is None) or (item is None) or (units is None):
        return {}

    condition = item.get('condition')
    if condition is None:
        return {}

    print(json.dumps(item, indent=4))

    speech = "Hoje em " + location.get('city') + ": " + condition.get('text') + \
             ", a temperatura é de " + condition.get('temp') + " " + units.get('temperature')

    print("Response:")
    print(speech)

    return {
        "speech": speech,
        "displayText": speech,
        # "data": data,
        # "contextOut": [],
        "source": "apiai-weather-webhook-sample"
    }


def _lookup_address(location):
    """
    Retrieve the coordinates of the location from googles geocode api.
    Limit of 2,000 requests a day
    """
    google_map_url = 'https://maps.googleapis.com/maps/api/geocode/json'
    payload = {'address': location}
    resp = requests.get(google_map_url, params=payload)
    try:
        resp.raise_for_status()
        results = resp.json()['results'][0]
        return {
            'lat': results['geometry']['location']['lat'],
            'lng': results['geometry']['location']['lng'],
            'address': results['formatted_address']
        }
    except (IndexError, KeyError):
        logger.error('unable to parse address return data: %d: %s', resp.status_code, resp.json())
        return None
    except (requests.exceptions.ConnectionError, requests.exceptions.HTTPError, requests.exceptions.Timeout):
        logger.error('unable to connect with maps.googleapis.com: %d - %s', resp.status_code, resp.text)
        return None


def _get_forecast_units(result):
    """
    Checks to see what uni the results were passed back as and sets the display units accordingly
    """
    units = {
        'temperature': 'F',
        'distance': 'Miles',
        'percipIntensity': 'in./hr.',
        'precipAccumulation': 'inches',
        'windSpeed': 'mph',
        'pressure': 'millibars'
    }
    if result['flags']:
        unit = result['flags']['units']
        if unit != 'us':
            units['temperature'] = 'C'
            units['distance'] = 'KM'
            units['percipIntensity'] = 'milimeters per hour'
            units['precipAccumulation'] = 'centimeters'
            units['windSpeed'] = 'm/s'
            units['pressure'] = 'kPa'
            if unit == 'ca':
                units['windSpeed'] = 'km/h'
            if unit == 'uk2':
                units['windSpeed'] = 'mph'
                units['distance'] = 'Miles'
    return units


def _lookup_weather(coords, api_key):
    """
    Retrieve the current forecast for the specified coordinates from forecast.io
    Limit of 1,000 requests a day
    """
    forecast_io_url = 'https://api.forecast.io/forecast/{0}/{1},{2}?units=auto'.format(api_key,
                                                                                       coords['lat'], coords['lng'])
    r = requests.get(forecast_io_url)

    try:
        j = r.json()
        current = {
            'address': coords['address'],
            'time': j['currently']['time'],
            'summary': j['currently']['summary'],
            'temperature': Decimal(j['currently']['temperature']),
            'feelsLike': Decimal(j['currently']['apparentTemperature']),
            'units': _get_forecast_units(j),
            'humidity': int(j['currently']['humidity'] * 100),
            'windspeed': Decimal(j['currently']['windSpeed']),
            'windbearing': j['currently']['windBearing'],
            'pressure': j['currently']['pressure']
        }
        if current['units']['pressure'] == 'kPa':
            current['pressure'] = Decimal(current['pressure'] / 10)

        if 'hourly' in j:
            current['hourly'] = j['hourly']['summary']
        if 'daily' in j:
            current['daily'] = j['daily']['summary']

    except ValueError as e:
        logger.error("Forecast Error: {}".format(e))
        current = dict()
    except (requests.exceptions.ConnectionError, requests.exceptions.HTTPError, requests.exceptions.Timeout):
        logger.error('Unable to connect with api.forecast.io: %d - %s', r.status_code, r.text)
        return None

    return current


def _get_wind_direction(degrees):
    """
    Determines the direction the wind is blowing from based off the degree passed from the API
    0 degrees is true north
    """
    wind_direction_text = "N"
    if 5 <= degrees < 40:
        wind_direction_text = "NNE"
    elif 40 <= degrees < 50:
        wind_direction_text = "NE"
    elif 50 <= degrees < 85:
        wind_direction_text = "ENE"
    elif 85 <= degrees < 95:
        wind_direction_text = "E"
    elif 95 <= degrees < 130:
        wind_direction_text = "ESE"
    elif 130 <= degrees < 140:
        wind_direction_text = "SE"
    elif 140 <= degrees < 175:
        wind_direction_text = "SSE"
    elif 175 <= degrees < 185:
        wind_direction_text = "S"
    elif 185 <= degrees < 220:
        wind_direction_text = "SSW"
    elif 220 <= degrees < 230:
        wind_direction_text = "SW"
    elif 230 <= degrees < 265:
        wind_direction_text = "WSW"
    elif 265 <= degrees < 275:
        wind_direction_text = "W"
    elif 275 <= degrees < 310:
        wind_direction_text = "WNW"
    elif 310 <= degrees < 320:
        wind_direction_text = "NW"
    elif 320 <= degrees < 355:
        wind_direction_text = "NNW"

    return wind_direction_text


def _format_current_weather(weather, locale_lang, default_english):
    """
    Formats the current weather data for the user.
    """
    weather_output_strings = []

    if 'temperature' in weather:
        weather_output_strings.append(
            "Atualmente está: <b>{0}°{1}</b>".format(round(weather['temperature'], 2),
                                                     weather['units']['temperature']))
    if 'address' in weather:
        weather_output_strings.append('em {0}\n'.format(weather['address']))
    if 'summary' in weather:
        weather_output_strings.append("<i>{0}</i>".format(weather['summary']))
    if 'feelsLike' in weather:
        weather_output_strings.append(
            "Sensação térmica atual de: {0}°{1}".format(round(weather['feelsLike'], 2),
                                                        weather['units']['temperature']))
    if 'windspeed' in weather:
        weather_output_strings.append(
            "Vento atual: {0} {1} from {2}".format(round(weather['windspeed'], 2), weather['units']['windSpeed'],
                                                   _get_wind_direction(weather['windbearing'])))
    if 'humidity' in weather:
        weather_output_strings.append("Humidade: {0}%".format(weather['humidity']))
    if 'pressure' in weather:
        weather_output_strings.append(
            "Pressão: {0} {1}".format(round(weather['pressure'], 2), weather['units']['pressure']))

    return "<br/>".join(weather_output_strings)


def _get_weather(bot, event, params):
    """
    Checks memory for a default location set for the current hangout.
    If one is not found and parameters were specified attempts to look up a location.
    If it finds a location it then attempts to load the weather data
    """
    parameters = list(params)
    location = {}

    address = ''.join(parameters).strip()
    location = _lookup_address(address)

    if location:
        return _lookup_weather(location, bot.get_config_option('forecast_api_key'))

    return {}


def weather_request_hangouts(*args):
    """Returns weather information from Forecast.io
    <b>/bot weather <location></b> Get location's current weather.
    <b>/bot weather</b> Get the hangouts default location's current weather. If the default location is not set talk to a hangout admin.
    """
    weather = _get_weather(args)
    if weather:
        return _format_current_weather(weather)
    else:
        return 'Puxa... Não consegui adquirir a previsão do tempo atual para este lugar. ' \
               'Acho que você vai precisar dar uma olhada lá fora.'


if __name__ == '__main__':
    port = int(os.getenv('PORT', 5000))

    print("Starting app on port %d" % port)

    app.run(debug=False, port=port, host='0.0.0.0')
