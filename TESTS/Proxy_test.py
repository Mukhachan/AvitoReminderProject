import sys
sys.path.append('..')

import requests
from random import randint
from config import proxies
proxies = {
            'https' : proxies[randint(0, len(proxies) - 1)],
            'http' : proxies[randint(0, len(proxies) - 1)]
        }
headers = {
            "User-Agent": "Mozilla/5.0 (Linux; Android 6.0; Nexus 5 Build/MRA58N) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/112.0.0.0 Mobile Safari/537.36",
        }


def proxy_request(url):
    response = requests.get(url, proxies=proxies)
    return response.text

print(proxy_request('http://httpbin.org/ip'))