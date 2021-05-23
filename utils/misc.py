#      FairGame - Automated Purchasing Program
#      Copyright (C) 2021  Hari Nagarajan
#
#      This program is free software: you can redistribute it and/or modify
#      it under the terms of the GNU General Public License as published by
#      the Free Software Foundation, either version 3 of the License, or
#      (at your option) any later version.
#
#      This program is distributed in the hope that it will be useful,
#      but WITHOUT ANY WARRANTY; without even the implied warranty of
#      MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#      GNU General Public License for more details.
#
#      You should have received a copy of the GNU General Public License
#      along with this program.  If not, see <https://www.gnu.org/licenses/>.
#
#      The author may be contacted through the project's GitHub, at:
#      https://github.com/Hari-Nagarajan/fairgame

from typing import Optional, List
from itertools import cycle

import os
import json

import time
from datetime import datetime

import psutil
import requests

from lxml import html
from selenium import webdriver

from selenium.common.exceptions import (
    TimeoutException,
)
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

from utils.logger import log

BAD_PROXIES_PATH = "config/bad_proxies.json"
RESPONSE_COUNTER_PATH = "html_saves/response_counter.json"
DEFAULT_MAX_TIMEOUT = 5


def create_webdriver_wait(driver, wait_time=10):
    return WebDriverWait(driver, wait_time)


def get_webdriver_pids(driver):
    pid = driver.service.process.pid
    driver_process = psutil.Process(pid)
    children = driver_process.children(recursive=True)
    webdriver_child_pids = []
    for child in children:
        webdriver_child_pids.append(child.pid)
    return webdriver_child_pids


def get_timeout(timeout=DEFAULT_MAX_TIMEOUT):
    return time.time() + timeout


def wait_for_element_by_xpath(d, xpath, timeout=10):
    try:
        WebDriverWait(d, timeout).until(
            EC.presence_of_element_located((By.XPATH, xpath))
        )
    except TimeoutException:
        log.debug(f"failed to find {xpath}")
        return False

    return True


def join_xpaths(xpath_list, separator=" | "):
    return separator.join(xpath_list)


def get_timestamp_filename(name, extension):
    """Utility method to create a filename with a timestamp appended to the root and before
    the provided file extension"""
    now = datetime.now()
    date = now.strftime("%m-%d-%Y_%H_%M_%S")
    if extension.startswith("."):
        return name + "_" + date + extension
    else:
        return name + "_" + date + "." + extension


def transfer_selenium_cookies(
    d: webdriver.Chrome, s: requests.Session, cookie_list: Optional[List[str]] = None
):
    """Utility to transfer cookies from a Selenium webdriver session to a Requests session"""
    # get cookies, might use these for checkout later, with no cookies on
    # cookie_names = ["session-id", "ubid-main", "x-main", "at-main", "sess-at-main"]
    # for c in self.driver.get_cookies():
    #     if c["name"] in cookie_names:
    #         self.amazon_cookies[c["name"]] = c["value"]

    # update session with cookies from Selenium
    all_cookies = False
    if cookie_list is None:
        all_cookies = True
    # cookie_names = ["session-id", "ubid-main", "x-main", "at-main", "sess-at-main"]
    for c in d.get_cookies():
        if all_cookies or c["name"] in cookie_list:
            s.cookies.set(name=c["name"], value=c["value"])
            log.dev(f'Set Cookie {c["name"]} as value {c["value"]}')


def save_html_response(filename, status, body):
    """Saves response body"""
    file_name = get_timestamp_filename(
        "html_saves/" + filename + "_" + str(status) + "_requests_source", "html"
    )
    if body is None:
        body = ""
    page_source = body
    with open(file_name, "w", encoding="utf-8") as f:
        f.write(page_source)


def check_response(response_text):
    if response_text is None:
        return None
    # Check response text is valid
    payload = str(response_text)
    if payload is None or len(payload) == 0:
        log.debug("Empty response")
        return None
    log.debug(f"payload is {len(payload)} bytes")
    # Get parsed html, if there is an error during parsing, it will return None.
    return parse_html_source(payload)


def parse_html_source(data):
    tree = None
    try:
        tree = html.fromstring(data)
    except html.etree.ParserError:
        log.debug("html parser error")
    return tree


class UserAgentBook:
    def __init__(self, fp="config/user_agents.json"):
        self.fp = fp
        self.user_agents = dict()
        if os.path.exists(fp):
            with open(fp) as f:
                self.user_agents = json.load(f)

    def save(self):
        with open(self.fp, "w") as f:
            json.dump(self.user_agents, f, indent=4)


class ItemsHandler:
    @classmethod
    def create_items_pool(cls, item_list):
        cls.item_ids = {}
        for item in item_list:
            cls.item_ids.update({item.id: time.time()})
        cls.items = cycle(item_list)

    @classmethod
    def pop(cls):
        return next(cls.items)

    @classmethod
    def check_last_access(cls, item, delay):
        last_access = cls.item_ids[item.id]
        difference = time.time() - last_access
        if difference < delay:
            return True
        cls.item_ids.update({item.id: time.time()})
        return False


class BadProxyCollector:
    @classmethod
    def start(cls):
        cls.last_save = time.time()
        cls.collection = set()

    @classmethod
    def record(cls, status, connector):
        url = str(connector.proxy_url)
        if status == 503:
            cls.collection.add(url)
        if status == 200 and url in cls.collection:
            cls.collection.discard(url)

    @classmethod
    def save(cls):
        if cls.collection:
            with open(BAD_PROXIES_PATH, "w") as f:
                temp = list(cls.collection)
                json.dump(temp, f, indent=4)
            cls.last_save = time.time()

    @classmethod
    def timer(cls):
        if time.time() - cls.last_save >= 300:
            return True
        return False

    @classmethod
    def bad_proxy_count(cls):
        return len(cls.collection)
    
class ResponseTracker:
    start_time = time.time()
    last_save = time.time()
    data = { "run_time": "",
             "200": 0,
             "200_rate": 0,
             "403" : 0,
             "403_rate": 0,
             "503" : 0,
             "503_rate": 0,
             "999" : 0,
             "999_rate": 0,
             "turbo": 0,
             "total": 0,
             "req_rate": 0 }

    @classmethod
    def config(cls, delay, asin_count, proxy_count):
        cls.delay = delay
        cls.asin_count = asin_count
        cls.proxy_count = proxy_count

    @classmethod
    def record(cls, status):
        log.debug(f"Tracking response {status}")

        if str(status) in cls.data:
            cls.data[str(status)] += 1
        else: 
            cls.data[str(status)] = 1

        cls.data["total"] += 1

        total_time = time.time() - cls.start_time
        cls.data["run_time"] = time.strftime("%H:%M:%S", time.gmtime(total_time))

        if status == "turbo":
            return

        cls.data["200_rate"] = f"{cls.data['200'] / cls.data['total'] * 100:.2f}%"
        cls.data["403_rate"] = f"{cls.data['403'] / cls.data['total'] * 100:.2f}%"
        cls.data["503_rate"] = f"{cls.data['503'] / cls.data['total'] * 100:.2f}%"
        cls.data["999_rate"] = f"{cls.data['999'] / cls.data['total'] * 100:.2f}%"
        cls.data["req_rate"] = f"{cls.data['total'] / total_time:.2f}/sec"

    @classmethod
    def save(cls):
        if cls.timer() and cls.data:
            try:
                bad_proxy_ct = BadProxyCollector.bad_proxy_count()
                cls.data["bad_proxies"] = bad_proxy_ct

                if cls.delay and cls.asin_count and cls.proxy_count:
                    proxy_rate = ((cls.proxy_count - bad_proxy_ct) / cls.asin_count) * cls.delay
                    cls.data["proxy_req_rate"] = f"{proxy_rate:.2f} sec/req"

                log.debug("Saving tracking info...")
                with open(RESPONSE_COUNTER_PATH, "w") as f:
                    json.dump(cls.data, f, indent=4, sort_keys=True)
            except Exception as e:
                log.error("Error writing stats")
                log.error(e)
            finally:
                cls.last_save = time.time()

    @classmethod
    def timer(cls):
        if time.time() - cls.last_save >= 1:
            return True
        return False
