import datetime

import sys
from PIL import Image, ImageDraw, ImageFont

import dataset
import logging

LOG = logging.getLogger(__name__)


def main(argv):
    db = dataset.connect('sqlite:///data.sqlite')
    table = db['data']

    for row in table.all():
        creator = ImageCreator(
            row['title'],
            row['penalty_amount'],
            row['abbreviated_description'],
            date=datetime.date.today()
        )
        if creator.success:
            creator.save('img/{}.png'.format(slugify(row['title'])))
        else:
            LOG.error('Failed for: {}'.format(row))


def slugify(title):
    import re
    return re.sub('[^A-Za-z0-9]+', '-', title)


class ImageCreator():
    WIDTH = 1200
    HEIGHT = 675

    LEFT_MARGIN = 100
    RIGHT_MARGIN = 50

    ORGANISATION_TOP_MARGIN = 50
    ORG_FONT_SIZE = 56
    ORG_MAX_WIDTH = WIDTH - LEFT_MARGIN - RIGHT_MARGIN

    PENALTY_TOP_MARGIN = 160
    PENALTY_FONT_SIZE = 120

    DESCRIPTION_TOP_MARGIN = 350
    DESCRIPTION_FONT_SIZE = 35
    DESCRIPTION_LINE_SPACING = 45
    DESCRIPTION_WRAP_WIDTH = 800

    DATE_TOP_MARGIN = 550
    DATE_FONT_SIZE = 45
    TEXT_COLOUR = (0, 0, 0)

    BOLD_FONT = 'media/helvetica-neue-bold.ttf'
    DESCRIPTION_FONT = 'media/FreeMonoBold.ttf'

    def __init__(self, organisation, penalty_amount, description, date):
        assert isinstance(date, datetime.date), date

        if description is None:
            LOG.warning('Description is None, not making image')
            self.success = False
            return

        self.organisation = organisation
        self.penalty_amount = penalty_amount
        self.description = description
        self.date = date

        self.load_canvas()
        self.add_org_title()
        self.add_penalty()
        self.add_description()
        self.add_date()

        self.success = True

    def save(self, filename='image.png'):
        self.im.save(filename)

    def load_canvas(self):
        """
        Load a blank image with dimensions 1200 x 675
        """
        self.im = Image.open('media/background.png')

    def add_org_title(self):
        font = ImageFont.truetype(self.BOLD_FONT, self.ORG_FONT_SIZE)

        draw = ImageDraw.Draw(self.im)

        for char_length in range(len(self.organisation), 0, -1):
            if char_length < len(self.organisation):
                text = '{}…'.format(self.organisation.upper()[0:char_length-1])
            else:
                text = self.organisation.upper()[0:char_length]

            width = font.getsize(text)[0]
            LOG.debug('width: {} `{}`'.format(width, text))

            if width <= self.ORG_MAX_WIDTH:
                draw.text(
                    (self.LEFT_MARGIN, self.ORGANISATION_TOP_MARGIN),
                    text,
                    self.TEXT_COLOUR,
                    font=font
                )
                return

    def add_penalty(self):
        if self.penalty_amount:
            font = ImageFont.truetype(self.BOLD_FONT, self.PENALTY_FONT_SIZE)
            draw = ImageDraw.Draw(self.im)
            draw.text(
                (self.LEFT_MARGIN, self.PENALTY_TOP_MARGIN),
                self.penalty_amount,
                self.TEXT_COLOUR,
                font=font
            )

    def add_description(self):
        font = ImageFont.truetype(
            self.DESCRIPTION_FONT, self.DESCRIPTION_FONT_SIZE
        )
        draw = ImageDraw.Draw(self.im)

        lines = self.wrap(
            self.description,
            font,
            self.DESCRIPTION_WRAP_WIDTH
        )

        if len(lines) > 4:
            lines = lines[0:4]
            lines[3] = '{}…'.format(lines[3][0:-1])

        for i, line in enumerate(lines):
            offset = i * self.DESCRIPTION_LINE_SPACING

            draw.text(
                (self.LEFT_MARGIN, self.DESCRIPTION_TOP_MARGIN + offset),
                line,
                self.TEXT_COLOUR,
                font=font
            )

    def add_date(self):
        font = ImageFont.truetype(self.BOLD_FONT, self.DATE_FONT_SIZE)
        draw = ImageDraw.Draw(self.im)
        draw.text(
            (self.LEFT_MARGIN, self.DATE_TOP_MARGIN),
            self.date.strftime('%-d %B %Y').upper(),
            self.TEXT_COLOUR,
            font=font
        )

    def wrap(self, words, font, line_length_px):
        lines = []

        line = ''

        for word in words.split(' '):
            line_longer = '{} {}'.format(line, word).strip()
            len_pixels = font.getsize(line_longer)[0]

            LOG.debug('len {} `{}`'.format(len_pixels, line_longer))
            if len_pixels > line_length_px:
                lines.append(line)
                line = word

            else:
                line = line_longer

        lines.append(line)

        LOG.debug(lines)
        return lines


if __name__ == '__main__':
    main(sys.argv)
