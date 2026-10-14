"""Conservative public staff-card suggestions; never infers buying authority."""
import re
from html.parser import HTMLParser
from urllib.parse import unquote

ROLE = re.compile(r"\b(?:managing partner|partner|president|vice president|chief [a-z ]{1,35} officer|CEO|CFO|CTO|owner|founder|co-founder|superintendent|principal|director(?: of [a-z &-]{1,60})?|(?:operations|office|business|marketing|IT|general|finance|communications|facilities|purchasing|procurement|technology) manager|communications officer|procurement officer)\b", re.I)
NAME = re.compile(r"^(?:(?:Dr\.?|Mr\.?|Ms\.?|Mrs\.?)\s+)?[A-Z][a-zA-Z'’-]+(?:\s+(?:[A-Z]\.?|[A-Z][a-zA-Z'’-]+)){1,4}(?:,?\s+(?:CPA|PhD|MBA|EdD))?$", re.UNICODE)
NOT_NAMES = {'contact', 'about', 'meet', 'team', 'staff', 'board', 'our', 'office', 'school', 'district', 'services', 'leadership', 'privacy', 'terms'}


def person_name(value):
    return bool(NAME.fullmatch(value) and not NOT_NAMES.intersection(value.lower().split()))


class StaffParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack, self.blocks = [], []
        self.hidden = 0

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag in {'script', 'style', 'template', 'svg'}:
            self.hidden += 1
        card = tag in {'article', 'li', 'div', 'section'} and re.search(r'(?:staff|team|person|member|profile)[-_ ]?(?:card|member|item|bio)?', attrs.get('class', ''), re.I)
        if tag in {'h2', 'h3', 'h4', 'p'} or card:
            self.stack.append({'tag': tag, 'card': bool(card), 'parts': [], 'email': '', 'phone': ''})
        if tag == 'a' and not self.hidden:
            href = attrs.get('href', '')
            for block in self.stack:
                if href.lower().startswith('mailto:'):
                    block['email'] = unquote(href[7:].split('?', 1)[0])
                elif href.lower().startswith('tel:'):
                    block['phone'] = unquote(href[4:])

    def handle_data(self, data):
        if not self.hidden:
            for block in self.stack:
                if sum(map(len, block['parts'])) < 1600:
                    block['parts'].append(data)

    def handle_endtag(self, tag):
        if tag in {'script', 'style', 'template', 'svg'}:
            self.hidden = max(0, self.hidden-1)
        for index in range(len(self.stack)-1, -1, -1):
            if self.stack[index]['tag'] == tag:
                block = self.stack.pop(index)
                block['text'] = ' '.join(' '.join(block['parts']).split())
                if block['text']:
                    self.blocks.append(block)
                break


def extract_staff(page, observed_at):
    parser = StaffParser()
    parser.feed(page['text'])
    from business_research import email, phone
    candidates = []

    def add(name, role, block):
        if not person_name(name) or len(block['text']) > 700:
            return
        candidates.append({'name': name, 'role': role, 'email': email(block['email']) or '', 'phone': phone(block['phone']) or '',
            'excerpt': block['text'], 'source_url': page['url'], 'observed_at': observed_at,
            'verification': 'observed_staff_text_unreviewed', 'limitation': 'Review person, organization, and role; purchasing authority is unknown'})

    for index, block in enumerate(parser.blocks):
        text = block['text']
        # Adjacent name heading and explicit role paragraph.
        if block['tag'] in {'h2', 'h3', 'h4'} and person_name(text) and index+1 < len(parser.blocks):
            following = parser.blocks[index+1]
            match = ROLE.search(following['text'])
            if match and following['tag'] == 'p' and len(following['text']) < 200:
                add(text, match.group(), {**following, 'text': text+' — '+following['text']})
        # A single bounded card with a name followed immediately by a role.
        match = ROLE.search(text)
        if match and (block['card'] or block['tag'] in {'p', 'h2', 'h3', 'h4'}):
            before = text[:match.start()].strip(' —–-|,:')
            add(before, match.group(), block)
    return list({(p['name'].casefold(), p['role'].casefold(), p['source_url']): p for p in candidates}.values())[:25]
