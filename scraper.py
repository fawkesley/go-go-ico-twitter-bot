#!/usr/bin/env python3

import datetime
import logging
import os
import sys
import re

from pprint import pprint

import dataset
import requests_cache
import lxml.html

ONE_HOUR = datetime.timedelta(hours=1)


class RequestsWrapper():
    def __init__(self):
        self.session = requests_cache.core.CachedSession(expire_after=ONE_HOUR)

    def get(self, url, *args, **kwargs):
        return self.session.get(url, *args, **kwargs)


def main(output_dir=None):
    logging.basicConfig(level=logging.DEBUG)
    scraper = ICOPenaltyScraper(RequestsWrapper())

    db = dataset.connect('sqlite:///data.sqlite')
    table = db['data']

    for row in scraper.run():
        pprint(row)
        table.upsert(row, ['url'])


class ICOPenaltyScraper():
    BASE_URL = 'https://ico.org.uk'
    LIST_URL = '{}/action-weve-taken/enforcement/'.format(BASE_URL)  # noqa

    XPATH_LIST_PAGE_LINK = '//a[contains(@href, "/action-weve-taken/enforcement/")]'  # noqa
    XPATH_PDF_LINK = "//div[contains(@class, 'resultlist')]//a[contains(@href, '/media/action-weve-taken') and contains(@href, '.pdf')]"  # noqa
    XPATH_DATE = "//dt[contains(text(), 'Date')]/following-sibling::dd[1]"  # noqa
    XPATH_DESCRIPTION = "//div[contains(@class, 'article-content')]/p"

    def __init__(self, requests_like_object):
        self.http = requests_like_object
        self.penalty_pages = None
        self.actions = None

    def run(self):
        self.parse_list_page()

        for url in self.penalty_pages:
            yield self.parse_extra_data_from_penalty_page(url)

    @staticmethod
    def mkdir_p(directory):
        if not os.path.isdir(directory):
            os.makedirs(directory)
        return directory

    def parse_list_page(self):
        root = self._get_as_lxml(self.LIST_URL)

        self.penalty_pages = [
            self._expand_href(a.attrib['href']) for a in root.xpath(
                self.XPATH_LIST_PAGE_LINK)
        ]
        self.penalty_pages = list(filter(
            lambda url: url != self.LIST_URL,
            self.penalty_pages))

        pprint(self.penalty_pages)

    def parse_extra_data_from_penalty_page(self, url):
        """
        Return a PDF() object for PDF URL linked in the penalty page.
        """
        root = self._get_as_lxml(url)
        pdf_url = self._parse_pdf_url(root, url)

        return {
            'url': url,
            'pdf_id': self._parse_id(pdf_url),
            'pdf_url': pdf_url,
            'type': self._parse_type(pdf_url),
            'date': self._parse_date(root),
            'title': self._parse_title(root),
            'description': self._parse_description(root)
        }

    def _parse_pdf_url(self, lxml_root, url):
        a_tags = lxml_root.xpath(self.XPATH_PDF_LINK)

        if len(a_tags) == 0:
            logging.info("Couldn't find a PDF on page {}".format(url))

        elif len(a_tags) == 1:
            return self._expand_href(a_tags[0].attrib['href'])

        else:
            raise RuntimeError('Multiple PDF links: on page {} {}'.format(
                url, a_tags))

    def _parse_title(self, lxml_root):
        h1s = lxml_root.xpath('//h1')
        if len(h1s) == 1:
            return h1s[0].text_content().strip()

    def _parse_description(self, lxml_root):
        ps = lxml_root.xpath(self.XPATH_DESCRIPTION)
        if len(ps) >= 1:
            return ps[0].text_content().strip()
        else:
            raise RuntimeError(len(ps))

    def _parse_date(self, lxml_root):
        def parse(date_string):
            "e.g. 21 December 2017"
            return datetime.datetime.strptime(
                date_string, '%d %B %Y'
            ).date().isoformat()

        dates = lxml_root.xpath(self.XPATH_DATE)
        if len(dates) == 1:
            return parse(dates[0].text_content().strip())

    def _parse_id(self, pdf_url):
        if pdf_url is None:
            return None

        match = re.search('\/(?P<id>\d+)\/', pdf_url)
        if match:
            return match.group('id')

    def _parse_type(self, pdf_url):
        if pdf_url is None:
            return None

        match = re.search('\/action-weve-taken\/(?P<type>.+?)\/', pdf_url)
        if match:
            type_slug = match.group('type')

            return {
                'enforcement-notices': 'enforcement-notice',
                'mpns': 'monetary-penalty',
                'undertakings': 'undertaking',
            }.get(type_slug, None)

    def _get_as_lxml(self, url):
        logging.info(url)
        response = self.http.get(url)
        response.raise_for_status()

        if response.status_code == 301:
            raise RuntimeError(response.headers)

        return lxml.html.fromstring(response.text)

    def _expand_href(self, href):
        if href.startswith('/'):  # not complete
            return '{}{}'.format(self.BASE_URL, href)
        else:
            return href


if __name__ == '__main__':
    main(*sys.argv[1:])
