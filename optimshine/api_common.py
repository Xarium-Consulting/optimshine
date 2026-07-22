#!/usr/bin/env python
#
# Copyright 2025 Norbert Kamiński <norbert.kaminski@xarium.world>
#
# SPDX-License-Identifier: LGPL-3.0-or-later
#

import datetime
import requests

from logging import RootLogger

HEADERS = {
    "Content-Type": "application/json",
    "lang": "en_US",
    "User-Agent": "Mozilla/5.0"
}


class ApiCommon:
    """
    A class to handle common API operations such as sending POST and
    GET requests.
    """
    def __init__(self, log: RootLogger):
        self.log = log

    def api_post_request(self, api_url, request, token=None):
        """
        Sends a POST request to the specified API URL with the given
        request data.

        Args:
            api_url (str): The URL of the API endpoint to send the
                           request to.
            request (dict): The JSON data to be sent in the request body.
            token (str, optional): An optional authorization token to
                                   include in the request headers.

        Returns:
            dict or None: The JSON response from the API if the request
                          is successful (status code 200), or None if
                          the request fails or the response cannot
                          be decoded.
        """
        headers = HEADERS.copy()
        if token:
            headers.update({"Authorization": token})
        response = requests.post(
            api_url,
            json=request,
            headers=headers
        )

        if response.status_code != 200:
            self.log.error(
                f"API post failed. Status code {response.status_code}"
            )
            return None

        try:
            return response.json()
        except requests.exceptions.JSONDecodeError:
            self.log.error(
                f"Failed to decode response message. Response: {response.text}"
            )
            return None

    def api_get_request(self, api_url, extra_headers=None):
        """
        Sends a GET request to the specified API URL and returns
        the JSON response.

        Args:
            api_url (str): The URL of the API endpoint to send the GET
                           request to.
            extra_headers (dict, optional): Additional headers to merge into
                                            the default request headers, for
                                            example an API key header.

        Returns:
            dict or None: The JSON response from the API if the request is
                          successful and the response can be decoded,
                          None if the request fails or the response cannot
                          be decoded.
        """
        headers = HEADERS.copy()
        if extra_headers:
            headers.update(extra_headers)
        response = requests.get(
            api_url,
            headers=headers
        )

        if response.status_code != 200:
            self.log.error(
                f"API get failed. Status code {response.status_code}"
            )
            return None

        try:
            return response.json()
        except requests.exceptions.JSONDecodeError:
            self.log.error(
                f"Failed to decode response message. Response: {response.text}"
            )
            return None

    def get_request_time(self, delta=None, future=False):
        """
        Get the current time adjusted by a specified delta.

        Args:
            delta (datetime.timedelta, optional): The time delta to adjust the
                                                  current time.
            future (bool, optional): If True, adds the delta to the current
                                     time; if False, subtracts the delta from
                                     the current time.

        Returns:
            str: The formatted current time as a string in
                 "YYYY-MM-DD HH:MM:SS" format.
        """
        if not delta:
            now = datetime.datetime.now()
        elif future:
            now = datetime.datetime.now() + delta
        else:
            now = datetime.datetime.now() - delta
        return now.strftime("%Y-%m-%d %H:%M:%S")
