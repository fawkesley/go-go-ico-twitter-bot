#!/usr/bin/env python3

import datetime
import logging
import os
import sys
import tempfile
import re

import dataset
import requests_cache
import tweepy
import lxml.html

from image_creator import ImageCreator

ONE_HOUR = datetime.timedelta(hours=1)

TWITTER_CONSUMER_KEY = os.environ['MORPH_TWITTER_CONSUMER_KEY'].strip()
TWITTER_CONSUMER_SECRET = os.environ['MORPH_TWITTER_CONSUMER_SECRET'].strip()
TWITTER_ACCESS_TOKEN = os.environ['MORPH_TWITTER_ACCESS_TOKEN'].strip()
TWITTER_ACCESS_TOKEN_SECRET = os.environ['MORPH_TWITTER_ACCESS_TOKEN_SECRET'].strip()

ICO_NAMES = [
    "The Information Commissioner’s Office (ICO)",
    "The Information Commissioner’s Office",
    "the Information Commissioner’s Office (ICO)",
    "the Information Commissioner’s Office",
    "the Information Commissioner",
    "the ico",
    "the ICO",
]

DEBUG = os.environ.get('MORPH_DEBUG', 'false') in ('1', 'true', 'yes')


class RequestsWrapper():
    def __init__(self):
        self.session = requests_cache.core.CachedSession(expire_after=ONE_HOUR)

    def get(self, url, *args, **kwargs):
        return self.session.get(url, *args, **kwargs)


def main(output_dir=None):
    logging.basicConfig(level=logging.DEBUG if DEBUG else logging.INFO)

    db = dataset.connect('sqlite:///data.sqlite')
    table = db['data']

    scrape_enforcements(table)

    db.commit()

    untweeted = get_untweeted(table)
    failed_tweets = tweet_untweeted(untweeted, db, table)

    if failed_tweets:
        logging.error('Failed to sent {} tweets'.format(failed_tweets))
        sys.exit(1)
    else:
        logging.info('Done.')


def get_untweeted(table):
    two_weeks_ago = datetime.date.today() - datetime.timedelta(days=14)

    for row in table.find(tweet_sent=False, order_by='date'):

        if parse_date(row['date']) >= two_weeks_ago:
            row['date'] = parse_date(row['date'])
            yield row


def parse_date(iso_string):
    return datetime.date(*[int(part) for part in iso_string.split('-')])


def tweet_untweeted(untweeted, db, table):
    failed_tweets = 0

    tweepy_api = make_tweepy_api()

    for untweeted in untweeted:
        logging.info('Tweeting {}'.format(untweeted['url']))
        tweeter = Tweeter(tweepy_api, **untweeted)

        db.begin()
        try:
            tweeter.tweet()
        except Exception as e:
            failed_tweets += 1
            logging.exception(e)
            db.rollback()
            continue
        else:
            untweeted['tweet_sent'] = True
            table.upsert(untweeted, ['url'])
            db.commit()

    return failed_tweets


def scrape_enforcements(table):
    scraper = ICOPenaltyScraper(RequestsWrapper())

    for row in scraper.run():
        tweet_sent = table.find_one(
            url=row['url'],
            tweet_sent=True
        ) is not None

        row['tweet_sent'] = tweet_sent

        table.upsert(row, ['url'])


def make_tweepy_api():
    logging.debug(
        'consumer_key: `{}`, consumer_secret: `{}`, '
        'access_token: `{}`, access_token_secret: `{}`'.format(
            TWITTER_CONSUMER_KEY,
            TWITTER_CONSUMER_SECRET,
            TWITTER_ACCESS_TOKEN,
            TWITTER_ACCESS_TOKEN_SECRET
        )
    )

    auth = tweepy.OAuthHandler(
        TWITTER_CONSUMER_KEY,
        TWITTER_CONSUMER_SECRET
    )
    auth.set_access_token(
        TWITTER_ACCESS_TOKEN,
        TWITTER_ACCESS_TOKEN_SECRET
    )

    tweepy_api = tweepy.API(auth)

    try:
        tweepy_api.verify_credentials()
    except Exception as e:
        logging.exception(e)

        pass
        # raise RuntimeError('Twitter credentials invalid')
    else:
        logging.info('Twitter credentials verified')

    return tweepy_api


class Tweeter():
    # Note: this can change over time, see
    # https://developer.twitter.com/en/docs/developer-utilities/configuration/api-reference/get-help-configuration

    SHORT_URL_LENGTH = 23
    TWEET_LENGTH = 140

    def __init__(self, tweepy_api, url, title, description,
                 abbreviated_description, pdf_url, penalty_amount,
                 date, *args, **kwargs):
        self._url = url
        self._organisation = title
        self._description = description
        self._abbreviated_description = abbreviated_description
        self._pdf_url = pdf_url
        self._penalty_amount = penalty_amount
        self._date = date
        self._tweepy_api = tweepy_api

    def tweet(self):
        tweet = self.make_tweet(self._description, self._url)

        creator = ImageCreator(
            self._organisation,
            self._penalty_amount,
            self._abbreviated_description,
            self._date,
        )
        import time

        if creator.success:
            with tempfile.NamedTemporaryFile(suffix='.png') as f:
                creator.save(f.name)
                logging.info('Posting tweet & image in 60s: `{}` '
                             'img: {}'.format(tweet, f.name))
                time.sleep(60)

                # http://docs.tweepy.org/en/v3.5.0/api.html#API.update_with_media
                # https://developer.twitter.com/en/docs/tweets/post-and-engage/api-reference/post-statuses-update

                self._tweepy_api.update_with_media(f.name, tweet)
        else:
            logging.info('Posting in 60s: `{}`'.format(tweet))
            time.sleep(60)
            self._tweepy_api.update_status(tweet)

    @staticmethod
    def make_tweet(description, url):
        character_budget = Tweeter.TWEET_LENGTH - Tweeter.SHORT_URL_LENGTH - 1

        description = replace(
            description,
            ICO_NAMES,
            '@ICOnews'
        )

        if description.startswith('@'):
            description = '.{}'.format(description)

        if len(description) <= character_budget:
            short_desc = description
        else:
            short_desc = '{}…'.format(
                description[:character_budget - 1]
            )

        tweet = '{} {}'.format(short_desc, url)
        return tweet


def replace(long_text, replace_names, with_text):
    for name in replace_names:
        new = long_text.replace(name, with_text)
        if new != long_text:
            return new

    return long_text


def capitalize(string):
    return '{}{}'.format(string[0].upper(), string[1:])

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

        logging.info('Found {} penalty page URLs'.format(
            len(self.penalty_pages)
        ))
        logging.debug('Penalty pages: {}'.format(self.penalty_pages))

    def parse_extra_data_from_penalty_page(self, url):
        """
        Return a PDF() object for PDF URL linked in the penalty page.
        """
        root = self._get_as_lxml(url)
        pdf_url = self._parse_pdf_url(root, url)
        description = self._parse_description(root)
        penalty_amount = self._parse_penalty_amount(description)
        abbreviated = self._abbreviate_description(description)

        return {
            'url': url,
            'pdf_id': self._parse_id(pdf_url),
            'pdf_url': pdf_url,
            'type': self._parse_type(pdf_url),
            'date': self._parse_date(root),
            'title': self._parse_title(root),
            'description': description,
            'abbreviated_description': abbreviated,
            'penalty_amount': penalty_amount,
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

    def _parse_penalty_amount(self, description):
        if description is None:
            return None

        amounts = re.findall(r'£[0-9,]+\b', description)

        if len(amounts) == 1:
            return amounts[0]

        elif len(amounts) == 0:
            logging.info('No penalty amount found in `{}`'.format(description))

        elif len(amounts) > 1:
            logging.warning('{} penalty amount found in `{}`'.format(
                len(amounts), description)
            )

    @staticmethod
    def _abbreviate_description(description):
        if description is None:
            return None

        description = ICOPenaltyScraper._drop_initial_cruft(description)

        description = replace(
            description,
            ICO_NAMES,
            'the ICO'
        )

        description = replace(
            description,
            [
                'Telephone Preference Service (TPS)',
                'Telephone Preference Service',
            ],
            'TPS'
        )

        description = replace(
            description,
            [
                'Privacy and Electronic Communications (EC Directive) Regulations 2003',  # noqa
            ],
            'PECR'
        )
        return capitalize(description)

    @staticmethod
    def _drop_initial_cruft(description):
        """
        `Blah blah has been fined for...` -> `Fined for...`
        """

        phrases = [
            ('has been fined', 'fined'),
            ('has been prosecuted', 'prosecuted'),
        ]

        for phrase, replacement in phrases:
            phrase_position = description.find(phrase, 0, 100)

            if phrase_position != -1:
                remainder = description[phrase_position + len(phrase):]
                print('`{}` found at {} in `{}`, giving `{}`'.format(
                    phrase, phrase_position, description, remainder))

                return '{}{}'.format(replacement, remainder)

        return description

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
        logging.info('Parsing {}'.format(url))
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
