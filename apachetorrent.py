# VERSION: 1.26
# AUTHORS: bebetoh, mvsantss
# WEBSITE: https://apachetorrent.com
# LANGUAGE: pt_BR
# DESCRIPTION: qBittorrent search plugin for ApacheTorrent. Use only for content you have the right to download.

import html
import json
import re
import socket
import ssl
import sys
import unicodedata
from datetime import datetime, timezone
from html.parser import HTMLParser
from typing import Dict, List, Mapping, Set, Tuple, Union
from urllib.parse import quote_plus, unquote, urljoin, urlsplit
from urllib.request import Request, urlopen

from helpers import retrieve_url
from novaprinter import prettyPrinter


BASE_URL = 'https://apachetorrent.com'
MAX_RESULTS = 50
REQUEST_TIMEOUT = 20
PUBLIC_DNS_URL = 'https://dns.google/resolve?name={host}&type=A'
USER_AGENT = (
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
    'AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126 Safari/537.36'
)

RESULT_CARD_CLASS = 'capaname'
DOWNLOAD_AREA_ID = 'lista_links'
INFO_AREA_CLASS = 'infos'

UNKNOWN_SIZE = '-1'
UNKNOWN_COUNT = -1
UNKNOWN_DATE = -1
MONTHS_PT_BR = {
    'janeiro': 1,
    'fevereiro': 2,
    'marco': 3,
    'abril': 4,
    'maio': 5,
    'junho': 6,
    'julho': 7,
    'agosto': 8,
    'setembro': 9,
    'outubro': 10,
    'novembro': 11,
    'dezembro': 12,
}


def attrs_to_dict(attrs: List[Tuple[str, Union[str, None]]]) -> Dict[str, str]:
    """Convert HTMLParser attrs into a predictable dictionary."""
    result = {}

    for key, value in attrs:
        result[key] = value if value is not None else ''

    return result


def clean_text(text: str) -> str:
    """Decode entities and collapse whitespace from scraped HTML text."""
    text = html.unescape(text or '')
    text = re.sub(r'\s+', ' ', text)
    return text.strip()


def normalize_text(text: str) -> str:
    """Lowercase and remove accents for category checks and label matching."""
    normalized = unicodedata.normalize('NFKD', text or '')
    ascii_text = normalized.encode('ascii', 'ignore').decode('ascii')
    return ascii_text.lower()


def clean_result_title(title: str) -> str:
    """Remove repetitive action words that make qBittorrent results noisy."""
    title = clean_text(title)
    title = re.sub(r'^BAIXAR\s+', '', title, flags=re.IGNORECASE)
    title = re.sub(r'\bDOWNLOAD\s+TORRENT\b', '', title, flags=re.IGNORECASE)
    title = re.sub(r'\bDOWNLOAD\b', '', title, flags=re.IGNORECASE)
    title = re.sub(r'\bTORRENT\b', '', title, flags=re.IGNORECASE)
    title = re.sub(r'\s+', ' ', title)
    return title.strip(' -')


def extract_info_hash(magnet: str) -> str:
    match = re.search(r'xt=urn:btih:([^&]+)', magnet or '', flags=re.IGNORECASE)

    if not match:
        return ''

    return match.group(1).upper()


def extract_magnet_name(magnet: str) -> str:
    match = re.search(r'[?&]dn=([^&]+)', magnet or '')

    if not match:
        return ''

    name = unquote(match.group(1))
    name = name.replace('.', ' ')
    name = re.sub(r'\s+', ' ', name)
    return name.strip()


def format_size_for_qbt(size_text: str) -> str:
    """qBittorrent accepts human-readable sizes from search plugins."""
    match = re.search(r'([\d.,]+)\s*(GB|MB|KB|B)', size_text or '', flags=re.IGNORECASE)

    if not match:
        return UNKNOWN_SIZE

    number = match.group(1).replace(',', '.')
    unit = match.group(2).upper()
    return number + ' ' + unit


def format_pub_date_for_qbt(date_text: str) -> int:
    """Convert Portuguese publication dates to the Unix timestamp qBittorrent expects."""
    normalized = normalize_text(date_text)
    match = re.search(r'(\d{1,2})\s+de\s+([a-z]+)\s+de\s+(\d{4})', normalized)

    if not match:
        return UNKNOWN_DATE

    day = int(match.group(1))
    month = MONTHS_PT_BR.get(match.group(2), 0)
    year = int(match.group(3))

    if not month:
        return UNKNOWN_DATE

    return int(datetime(year, month, day, tzinfo=timezone.utc).timestamp())


def decode_html(raw_content: bytes, content_type: str = '') -> str:
    """Decode ApacheTorrent pages, correcting occasional wrong charset headers."""
    charset_match = re.search(r'charset=([\w-]+)', content_type or '', flags=re.IGNORECASE)
    charset = charset_match.group(1) if charset_match else 'utf-8'
    decoded = raw_content.decode(charset, errors='replace')

    if '\ufffd' not in decoded:
        return decoded

    windows_decoded = raw_content.decode('windows-1252', errors='replace')

    if windows_decoded.count('\ufffd') < decoded.count('\ufffd'):
        return windows_decoded

    return decoded


class SearchResultsParser(HTMLParser):
    """Parse search result cards and keep only detail-page links."""

    def __init__(self, base_url: str) -> None:
        HTMLParser.__init__(self)
        self.base_url = base_url
        self.results: List[Dict[str, str]] = []

        self.inside_card = False
        self.card_depth = 0
        self.inside_title_link = False
        self.current_link = ''
        self.current_title = ''
        self.current_title_attr = ''

    def handle_starttag(self, tag: str, attrs: List[Tuple[str, Union[str, None]]]) -> None:
        params = attrs_to_dict(attrs)

        if tag == 'div' and RESULT_CARD_CLASS in params.get('class', '').split():
            self._start_card()
            return

        if not self.inside_card:
            return

        if tag == 'div':
            self.card_depth += 1

        if tag == 'a':
            self._capture_result_link(params)

    def handle_data(self, data: str) -> None:
        if not self.inside_card or not self.inside_title_link:
            return

        text = clean_text(data)

        if not text:
            return

        if self.current_title:
            self.current_title += ' '

        self.current_title += text

    def handle_endtag(self, tag: str) -> None:
        if tag == 'a' and self.inside_title_link:
            self.inside_title_link = False

        if tag != 'div' or not self.inside_card:
            return

        self.card_depth -= 1

        if self.card_depth <= 0:
            self._finish_card()

    def _start_card(self) -> None:
        self.inside_card = True
        self.card_depth = 1
        self.inside_title_link = False
        self.current_link = ''
        self.current_title = ''
        self.current_title_attr = ''

    def _capture_result_link(self, params: Mapping[str, str]) -> None:
        href = params.get('href', '')

        if not self._is_result_link(href):
            return

        self.current_link = urljoin(self.base_url, href)
        self.current_title_attr = clean_result_title(params.get('title', ''))
        self.inside_title_link = True

    def _finish_card(self) -> None:
        title = clean_result_title(self.current_title or self.current_title_attr)

        if self.current_link and title:
            self.results.append({
                'title': title,
                'desc_link': self.current_link,
            })

        self.inside_card = False
        self.card_depth = 0
        self.inside_title_link = False
        self.current_link = ''
        self.current_title = ''
        self.current_title_attr = ''

    def _is_result_link(self, href: str) -> bool:
        absolute_url = urljoin(self.base_url, href or '')
        url_lower = absolute_url.lower()

        return url_lower.startswith(self.base_url) and 'baixar-torrent' in url_lower


class DetailsParser(HTMLParser):
    """Parse a detail page for magnet links and optional metadata."""

    info_labels = [
        'Lancamento',
        'Generos',
        'Idioma',
        'Duracao',
        'Classificacao',
        'Nota da Critica',
        'Qualidade',
        'Formato',
        'Tamanho',
        'Video',
        'Servidores de Download',
    ]

    def __init__(self) -> None:
        HTMLParser.__init__(self)
        self.magnets: List[Dict[str, str]] = []
        self.info: Dict[str, str] = {}
        self.published_at = ''

        self.inside_download_area = False
        self.download_depth = 0
        self.capture_download_text = False
        self.current_download_text = ''

        self.inside_info_area = False
        self.info_depth = 0
        self.info_text = ''

        self.expect_publication_date = False

    def handle_starttag(self, tag: str, attrs: List[Tuple[str, Union[str, None]]]) -> None:
        params = attrs_to_dict(attrs)

        if tag == 'div' and params.get('id') == DOWNLOAD_AREA_ID:
            self._start_download_area()
            return

        if tag == 'div' and INFO_AREA_CLASS in params.get('class', '').split():
            self._start_info_area()
            return

        if self.inside_download_area:
            self._handle_download_starttag(tag, params)

        if self.inside_info_area and tag == 'div':
            self.info_depth += 1

    def handle_data(self, data: str) -> None:
        text = clean_text(data)

        if not text:
            return

        if self.inside_download_area and self.capture_download_text:
            self.current_download_text = self._append_text(self.current_download_text, text)

        if self.inside_info_area:
            self.info_text = self._append_text(self.info_text, text)

        self._capture_publication_date(text)

    def handle_endtag(self, tag: str) -> None:
        if tag == 'p' and self.capture_download_text:
            self.capture_download_text = False
            self.current_download_text = ''

        if tag == 'div' and self.inside_download_area:
            self.download_depth -= 1

            if self.download_depth <= 0:
                self.inside_download_area = False

        if tag == 'div' and self.inside_info_area:
            self.info_depth -= 1

            if self.info_depth <= 0:
                self.inside_info_area = False
                self.info = self._parse_info_text(self.info_text)

    def _start_download_area(self) -> None:
        self.inside_download_area = True
        self.download_depth = 1
        self.capture_download_text = False
        self.current_download_text = ''

    def _start_info_area(self) -> None:
        self.inside_info_area = True
        self.info_depth = 1
        self.info_text = ''

    def _handle_download_starttag(self, tag: str, params: Mapping[str, str]) -> None:
        if tag == 'div':
            self.download_depth += 1

        if tag == 'p':
            self.capture_download_text = True
            self.current_download_text = ''

        if tag != 'a':
            return

        href = params.get('href', '')

        if not href.startswith('magnet:?'):
            return

        self.magnets.append({
            'magnet': html.unescape(href),
            'title': clean_result_title(params.get('title', '') or self.current_download_text),
        })

    def _capture_publication_date(self, text: str) -> None:
        if 'data de publica' in normalize_text(text):
            self.expect_publication_date = True
            return

        if self.expect_publication_date:
            self.published_at = text
            self.expect_publication_date = False

    def _parse_info_text(self, text: str) -> Dict[str, str]:
        fields = {}
        normalized = normalize_text(text)

        # The page renders labels as plain text after <strong> tags. This regex
        # extracts each label until the next known label.
        for index, label in enumerate(self.info_labels):
            label_key = normalize_text(label)
            next_labels = [normalize_text(item) for item in self.info_labels[index + 1:]]
            pattern = re.escape(label_key) + r'\s*:\s*(.*?)'

            if next_labels:
                pattern += r'(?=\s+(?:' + '|'.join(re.escape(item) for item in next_labels) + r')\s*:|$)'
            else:
                pattern += r'$'

            match = re.search(pattern, normalized, flags=re.IGNORECASE)

            if match:
                fields[label_key] = match.group(1).strip()

        return fields

    def _append_text(self, current: str, text: str) -> str:
        if current:
            return current + ' ' + text

        return text


class apachetorrent:
    url = BASE_URL
    name = 'ApacheTorrent'
    supported_categories = {
        'all': 'all',
        'movies': 'movies',
        'tv': 'tv',
        'anime': 'anime',
    }

    def search(self, what: str, cat: str = 'all') -> None:
        search_html = self._retrieve(self._build_search_url(what), 'search')

        if not search_html:
            return

        parser = SearchResultsParser(self.url)
        parser.feed(search_html)
        parser.close()

        printed_count = 0
        seen_desc_links: Set[str] = set()

        for result in parser.results:
            desc_link = result.get('desc_link', '')

            if not desc_link or desc_link in seen_desc_links:
                continue

            seen_desc_links.add(desc_link)

            if not self._result_matches_category(result.get('title', ''), cat):
                continue

            remaining = MAX_RESULTS - printed_count
            detail_count = self._print_detail_page_results(result, remaining)

            if detail_count:
                printed_count += detail_count
            else:
                prettyPrinter(self._build_search_result_info(result))
                printed_count += 1

            if printed_count >= MAX_RESULTS:
                break

    def download_torrent(self, info: str) -> None:
        details_html = self._retrieve(info, 'download')

        if not details_html:
            raise ValueError('ApacheTorrent download page could not be loaded')

        parser = DetailsParser()
        parser.feed(details_html)
        parser.close()

        for magnet_item in parser.magnets:
            magnet = magnet_item.get('magnet', '')

            if magnet:
                print(magnet + ' ' + info)
                return

        raise ValueError('ApacheTorrent magnet link not found')

    def _build_search_url(self, what: str) -> str:
        query = unquote(what or '').replace('+', ' ')
        return self.url + '/index.php?s=' + quote_plus(query)

    def _retrieve(self, url: str, context: str) -> str:
        try:
            content = retrieve_url(url)

            if content and not self._looks_like_failed_response(content):
                return content

            print(f'ApacheTorrent {context} request returned invalid helper response', file=sys.stderr)
        except Exception as exc:  # pylint: disable=broad-exception-caught
            print(f'ApacheTorrent {context} request failed with qBittorrent helper: {exc}', file=sys.stderr)

        return self._retrieve_with_ssl_fallback(url, context)

    def _retrieve_with_ssl_fallback(self, url: str, context: str) -> str:
        # ApacheTorrent can present a certificate that fails Python hostname
        # validation. Browsers may still open it, but qBittorrent's helper can
        # return no results. This fallback reads only the HTML needed to search.
        ssl_context = ssl._create_unverified_context()  # pylint: disable=protected-access
        request = Request(url, headers={'User-Agent': USER_AGENT})

        try:
            with urlopen(request, timeout=REQUEST_TIMEOUT, context=ssl_context) as response:
                content_type = response.headers.get('content-type', '')
                content = decode_html(response.read(), content_type)

                if not self._looks_like_provider_block(content):
                    return content

                print(f'ApacheTorrent {context} request reached provider block page', file=sys.stderr)
        except Exception as exc:  # pylint: disable=broad-exception-caught
            print(f'ApacheTorrent {context} request failed with SSL fallback: {exc}', file=sys.stderr)

        return self._retrieve_with_direct_ip_fallback(url, context)

    def _retrieve_with_direct_ip_fallback(self, url: str, context: str) -> str:
        # Some networks poison the system DNS entry for apachetorrent.com. Resolve
        # with public DNS, then connect to the real Cloudflare IP while keeping
        # the original hostname in TLS SNI and the HTTP Host header.
        parsed = urlsplit(url)
        host = parsed.hostname or ''

        for ip_address in self._resolve_public_a_records(host):
            try:
                content = self._https_get_via_ip(url, ip_address)

                if content and not self._looks_like_provider_block(content):
                    return content
            except Exception as exc:  # pylint: disable=broad-exception-caught
                print(f'ApacheTorrent {context} direct IP request failed for {ip_address}: {exc}', file=sys.stderr)

        return ''

    def _resolve_public_a_records(self, host: str) -> List[str]:
        if not host:
            return []

        dns_url = PUBLIC_DNS_URL.format(host=quote_plus(host))
        request = Request(dns_url, headers={'Accept': 'application/dns-json', 'User-Agent': USER_AGENT})

        try:
            with urlopen(request, timeout=REQUEST_TIMEOUT) as response:
                data = json.loads(response.read().decode('utf-8', errors='replace'))
        except Exception as exc:  # pylint: disable=broad-exception-caught
            print(f'ApacheTorrent public DNS lookup failed: {exc}', file=sys.stderr)
            return []

        answers = data.get('Answer', [])
        return [
            item.get('data', '')
            for item in answers
            if item.get('type') == 1 and item.get('data')
        ]

    def _https_get_via_ip(self, url: str, ip_address: str) -> str:
        parsed = urlsplit(url)
        host = parsed.hostname or ''
        path = parsed.path or '/'

        if parsed.query:
            path += '?' + parsed.query

        ssl_context = ssl.create_default_context()

        with socket.create_connection((ip_address, 443), timeout=REQUEST_TIMEOUT) as sock:
            with ssl_context.wrap_socket(sock, server_hostname=host) as tls_socket:
                request = (
                    f'GET {path} HTTP/1.1\r\n'
                    f'Host: {host}\r\n'
                    f'User-Agent: {USER_AGENT}\r\n'
                    'Accept: text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8\r\n'
                    'Connection: close\r\n\r\n'
                )
                tls_socket.sendall(request.encode('ascii'))
                raw_response = self._read_all(tls_socket)

        headers, body = self._split_http_response(raw_response)
        status_line = headers.split('\r\n', 1)[0]

        if ' 200 ' not in status_line:
            raise RuntimeError(status_line)

        if re.search(r'transfer-encoding:\s*chunked', headers, flags=re.IGNORECASE):
            body = self._decode_chunked_body(body)

        return decode_html(body, headers)

    def _read_all(self, tls_socket: ssl.SSLSocket) -> bytes:
        chunks = []

        while True:
            chunk = tls_socket.recv(65536)

            if not chunk:
                break

            chunks.append(chunk)

        return b''.join(chunks)

    def _split_http_response(self, raw_response: bytes) -> Tuple[str, bytes]:
        header_bytes, _, body = raw_response.partition(b'\r\n\r\n')
        headers = header_bytes.decode('iso-8859-1', errors='replace')
        return headers, body

    def _decode_chunked_body(self, body: bytes) -> bytes:
        decoded = bytearray()
        position = 0

        while True:
            line_end = body.find(b'\r\n', position)

            if line_end == -1:
                break

            size_line = body[position:line_end].split(b';', 1)[0]
            chunk_size = int(size_line.strip() or b'0', 16)
            position = line_end + 2

            if chunk_size == 0:
                break

            decoded.extend(body[position:position + chunk_size])
            position += chunk_size + 2

        return bytes(decoded)

    def _looks_like_provider_block(self, content: str) -> bool:
        normalized = normalize_text(content)
        return 'bloqueio.zaaztelecom' in normalized or 'bloqueio' in normalized[:3000]

    def _looks_like_failed_response(self, content: str) -> bool:
        normalized = normalize_text(content)

        if not normalized.strip():
            return True

        if normalized.lstrip().startswith('connection error:'):
            return True

        return self._looks_like_provider_block(content)

    def _result_matches_category(self, title: str, cat: str) -> bool:
        if cat not in self.supported_categories or cat == 'all':
            return True

        normalized = normalize_text(title)

        if cat == 'movies':
            return 'filme' in normalized

        if cat == 'tv':
            return 'serie' in normalized or 'temporada' in normalized or 'minisserie' in normalized

        if cat == 'anime':
            return 'anime' in normalized or 'desenho' in normalized

        return True

    def _print_detail_page_results(self, result: Mapping[str, str], limit: int) -> int:
        desc_link = result.get('desc_link', '')

        if not desc_link or limit <= 0:
            return 0

        details_html = self._retrieve(desc_link, 'details')

        if not details_html:
            return 0

        parser = DetailsParser()
        parser.feed(details_html)
        parser.close()

        printed_count = 0
        seen_hashes: Set[str] = set()

        for magnet_item in parser.magnets:
            magnet = magnet_item.get('magnet', '')

            if not magnet:
                continue

            info_hash = extract_info_hash(magnet)

            if info_hash and info_hash in seen_hashes:
                continue

            if info_hash:
                seen_hashes.add(info_hash)

            prettyPrinter(self._build_torrent_info(result, magnet_item, parser))
            printed_count += 1

            if printed_count >= limit:
                break

        return printed_count

    def _build_search_result_info(self, result: Mapping[str, str]) -> Dict[str, Union[str, int]]:
        desc_link = result.get('desc_link', '')

        return {
            'link': desc_link,
            'name': clean_result_title(result.get('title', '')),
            'size': UNKNOWN_SIZE,
            'seeds': UNKNOWN_COUNT,
            'leech': UNKNOWN_COUNT,
            'engine_url': self.url,
            'desc_link': desc_link,
            'pub_date': UNKNOWN_DATE,
        }

    def _build_torrent_info(
        self,
        result: Mapping[str, str],
        magnet_item: Mapping[str, str],
        parser: DetailsParser,
    ) -> Dict[str, Union[str, int]]:
        magnet = magnet_item.get('magnet', '')

        return {
            'link': magnet,
            'name': self._build_result_name(result.get('title', ''), magnet_item.get('title', ''), magnet, parser.info),
            'size': format_size_for_qbt(parser.info.get('tamanho', '')),
            'seeds': UNKNOWN_COUNT,
            'leech': UNKNOWN_COUNT,
            'engine_url': self.url,
            'desc_link': result.get('desc_link', ''),
            'pub_date': format_pub_date_for_qbt(parser.published_at),
        }

    def _build_result_name(
        self,
        base_title: str,
        magnet_title: str,
        magnet: str,
        info: Mapping[str, str],
    ) -> str:
        parts = [clean_result_title(base_title)]
        magnet_label = clean_result_title(magnet_title)

        # Avoid repeating the page title when the button title already includes it.
        if magnet_label and normalize_text(magnet_label) not in normalize_text(base_title):
            parts.append(magnet_label)

        details = ' / '.join(item for item in [
            info.get('qualidade', ''),
            info.get('idioma', ''),
            info.get('formato', ''),
        ] if item)

        if details:
            parts.append(details)

        if len(parts) == 1:
            magnet_name = extract_magnet_name(magnet)

            if magnet_name:
                parts.append(magnet_name)

        name = ' - '.join(item for item in parts if item)
        name = re.sub(r'\s+', ' ', name)
        return name.strip(' -')
