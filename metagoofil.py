#!/usr/bin/env python

# Standard Python libraries.
import argparse
import base64
import os
import queue
import random
import sys
import threading
import time
import urllib


# Third party Python libraries.
import googlesearch
import requests
from bs4 import BeautifulSoup

# https://stackoverflow.com/questions/27981545/suppress-insecurerequestwarning-unverified-https-request-is-being-made-in-pytho
from requests.packages.urllib3.exceptions import InsecureRequestWarning

requests.packages.urllib3.disable_warnings(InsecureRequestWarning)


__version__ = "1.5.0"


class DownloadWorker(threading.Thread):
    def __init__(self, metagoofil):
        threading.Thread.__init__(self)
        self.mg = metagoofil

    def run(self):
        while True:
            url = self.mg.queue.get()

            try:
                headers = {}

                if self.mg.user_agent is None:
                    user_agent_choice = random.choice(self.mg.random_user_agents).strip()
                    headers["User-Agent"] = f"{user_agent_choice}"
                else:
                    headers["User-Agent"] = self.mg.user_agent

                response = requests.get(
                    url,
                    headers=headers,
                    verify=False,
                    timeout=self.mg.url_timeout,
                    stream=True,
                )

                if response.status_code == 200:
                    try:
                        size = int(response.headers["Content-Length"])

                    except KeyError as e:
                        print(
                            f"[-] Exception for url: {url} -- {e} does not exist. Extracting file size from "
                            "response.content length."
                        )
                        size = len(response.content)

                    self.mg.total_bytes += size

                    url_file_name = str(response.url.strip("/").split("/")[-1])
                    filename = urllib.parse.unquote(url_file_name, encoding="utf-8")

                    print(f'[+] Downloading "{filename}" [{size} bytes] from: {response.url}')

                    with open(os.path.join(self.mg.save_directory, filename), "wb") as fh:
                        for chunk in response.iter_content(chunk_size=1024):
                            if chunk:
                                fh.write(chunk)

                else:
                    print(f"[-] URL {url} returned HTTP code {response.status_code}")

            except requests.exceptions.RequestException as e:
                print(f"[-] Exception for url: {url} -- {e}")

            self.mg.queue.task_done()


class Metagoofil:
    """The Metagoofil Class"""

    def __init__(
        self,
        domain,
        delay,
        save_links,
        url_timeout,
        search_max,
        download_file_limit,
        save_directory,
        number_of_threads,
        file_types,
        user_agent,
        download_files,
        search_engines,
        tor,
    ):
        self.domain = domain
        self.delay = delay
        self.save_links = open(save_links, "a") if save_links else None
        self.url_timeout = url_timeout
        self.search_max = search_max
        self.download_file_limit = download_file_limit
        self.save_directory = save_directory

        # Create queue and specify the number of worker threads.
        self.queue = queue.Queue()
        self.number_of_threads = number_of_threads

        self.file_types = file_types

        self.user_agent = user_agent
        # Populate a list of random User-Agents.
        with open("user_agents.txt") as fp:
            self.random_user_agents = fp.readlines()
        if self.user_agent is None:
            self.effective_ua = random.choice(self.random_user_agents).strip()
        else:
            self.effective_ua = self.user_agent

        self.download_files = download_files
        self.total_bytes = 0
        self.search_engines = search_engines
        self.tor = tor

    def go(self):
        for i in range(self.number_of_threads):
            thread = DownloadWorker(self)
            thread.daemon = True
            thread.start()

        if "ALL" in self.file_types:
            from itertools import product
            from string import ascii_lowercase

            # Generate all three letter combinations.
            self.file_types = ["".join(i) for i in product(ascii_lowercase, repeat=3)]

        for filetype in self.file_types:
            # Stores URLs with files, clear out for each filetype.
            self.files = []

            query = f"filetype:{filetype} site:{self.domain}"

            # Search across selected engines
            for engine in self.search_engines:
                print(
                    f"[*] Searching {engine} for {self.search_max} .{filetype} files "
                    f"and waiting {self.delay} seconds between searches"
                )

                try:
                    if engine == "google":
                        urls = search_google(query, self.search_max, self.delay, self.effective_ua, self.tor)
                    elif engine == "duckduckgo":
                        urls = search_duckduckgo(query, self.search_max, self.delay, self.effective_ua, self.tor)
                    elif engine == "startpage":
                        urls = search_startpage(query, self.search_max, self.delay, self.effective_ua, self.tor)
                    elif engine == "searxng":
                        urls = search_searxng(query, self.search_max, self.delay, self.effective_ua, self.tor)
                    elif engine == "metager":
                        urls = search_metager(query, self.search_max, self.delay, self.effective_ua, self.tor)
                    elif engine == "mojeek":
                        urls = search_mojeek(query, self.search_max, self.delay, self.effective_ua, self.tor)
                    else:
                        print(f"[-] Unknown search engine: {engine}")
                        continue

                    self.files.extend(urls)
                    print(f"[*] {engine} returned {len(urls)} results")

                except Exception as e:
                    print(f"[-] {engine} EXCEPTION: {e}")

            # Deduplicate while preserving order.
            self.files = list(dict.fromkeys(self.files))

            # Ensure the file list only contains the requested amount.
            if len(self.files) > self.search_max:
                self.files = self.files[:self.search_max]

            # Download files if specified with -w switch.
            if self.download_files:
                self.download()

            # Otherwise, just display them.
            else:
                print(f"[*] Results: {len(self.files)} .{filetype} files found")
                for file_name in self.files:
                    print(file_name)

            # Save links to output to file.
            if self.save_links:
                for f in self.files:
                    self.save_links.write(f"{f}\n")

        if self.save_links:
            self.save_links.close()

        if self.download_files:
            print(
                "[+] Total download: {} bytes / {:.2f} KB / {:.2f} MB".format(
                    self.total_bytes, self.total_bytes / 1024, self.total_bytes / (1024 * 1024)
                )
            )

    def download(self):
        self.counter = 1
        for url in self.files:
            if self.counter <= self.download_file_limit:
                self.queue.put(url)
                self.counter += 1

        self.queue.join()


# ---- Search engine implementations ----


def search_google(query, stop, pause, user_agent, tor=False):
    urls = []
    proxies = _get_tor_proxies(tor)
    if proxies:
        headers = {"User-Agent": user_agent}
        start = 0
        while len(urls) < stop:
            params = {"q": query, "start": start, "num": 100, "filter": "0"}
            try:
                resp = requests.get(
                    "https://www.google.com/search",
                    params=params,
                    headers=headers,
                    proxies=proxies,
                    timeout=15,
                )
                if resp.status_code != 200:
                    break
                soup = BeautifulSoup(resp.text, "html.parser")
                before = len(urls)
                for a in soup.find_all("a", href=True):
                    href = a["href"]
                    if href.startswith("/url?q="):
                        parsed = urllib.parse.urlparse(href)
                        qs = urllib.parse.parse_qs(parsed.query)
                        actual = qs.get("q", [None])[0]
                        if actual and actual.startswith("http") and actual not in urls:
                            urls.append(actual)
                    elif href.startswith("http") and "google.com" not in href:
                        if href not in urls:
                            urls.append(href)
                    if len(urls) >= stop:
                        break
                if len(urls) == before:
                    break
                start += 100
                time.sleep(pause)
            except requests.exceptions.RequestException as e:
                print(f"[-] Google request error: {e}")
                break
    else:
        try:
            for url in googlesearch.search(
                query,
                start=0,
                stop=stop,
                num=100,
                pause=pause,
                extra_params={"filter": "0"},
                user_agent=user_agent,
            ):
                urls.append(url)
        except Exception as e:
            print(f"[-] Google EXCEPTION: {e}")
    return urls


SEARXNG_INSTANCES = [
    os.environ.get("SEARXNG_INSTANCE", "https://searx.be"),
    "https://search.sapti.me",
    "https://priv.au",
    "https://searx.perennialte.ch",
    "https://searx.work",
]


def search_searxng(query, stop, pause, user_agent, tor=False):
    headers = {"User-Agent": user_agent}
    urls = []
    proxies = _get_tor_proxies(tor)

    for instance in SEARXNG_INSTANCES:
        if len(urls) >= stop:
            break
        params = {"q": query, "format": "html"}
        print(f"[*]   Using SearXNG instance: {instance}")
        try:
            resp = requests.get(
                f"{instance}/search",
                params=params,
                headers=headers,
                proxies=proxies,
                timeout=15,
            )
            if resp.status_code != 200:
                continue

            soup = BeautifulSoup(resp.text, "html.parser")
            for article in soup.select("article.result"):
                a = article.select_one("h3 a")
                if not a:
                    a = article.select_one("a.url_header")
                if not a:
                    continue
                href = a.get("href")
                if href and href.startswith("http") and href not in urls:
                    urls.append(href)
                    if len(urls) >= stop:
                        break

            if urls:
                break

        except requests.exceptions.RequestException as e:
            print(f"[-] SearXNG ({instance}) request error: {e}")
            continue

    return urls


def search_metager(query, stop, pause, user_agent, tor=False):
    headers = {"User-Agent": user_agent}
    urls = []
    proxies = _get_tor_proxies(tor)
    offset = 0

    while len(urls) < stop:
        params = {"q": query, "offset": offset}
        try:
            resp = requests.get(
                "https://metager.org/meta/meta.ger3",
                params=params,
                headers=headers,
                proxies=proxies,
                timeout=15,
            )
            if resp.status_code != 200:
                break

            soup = BeautifulSoup(resp.text, "html.parser")
            links = soup.select("h3.result-title a")

            if not links:
                break

            before = len(urls)
            for a in links:
                href = a.get("href")
                if href and href.startswith("http") and href not in urls:
                    urls.append(href)
                    if len(urls) >= stop:
                        break

            if len(urls) == before:
                break

            offset += 10
            time.sleep(pause)

        except requests.exceptions.RequestException as e:
            print(f"[-] MetaGer request error: {e}")
            break

    return urls


def search_mojeek(query, stop, pause, user_agent, tor=False):
    headers = {"User-Agent": user_agent}
    urls = []
    proxies = _get_tor_proxies(tor)
    page = 1

    while len(urls) < stop:
        params = {"q": query, "s": page}
        try:
            resp = requests.get(
                "https://www.mojeek.com/search",
                params=params,
                headers=headers,
                proxies=proxies,
                timeout=15,
            )
            if resp.status_code != 200:
                break

            soup = BeautifulSoup(resp.text, "html.parser")
            links = soup.select("a.title, h2 a")

            if not links:
                break

            before = len(urls)
            for a in links:
                href = a.get("href")
                if href and href.startswith("http") and href not in urls:
                    urls.append(href)
                    if len(urls) >= stop:
                        break

            if len(urls) == before:
                break

            page += 1
            time.sleep(pause)

        except requests.exceptions.RequestException as e:
            print(f"[-] Mojeek request error: {e}")
            break

    return urls


_tor_cache = None


def _get_tor_proxies(tor):
    global _tor_cache
    if _tor_cache is not None:
        return _tor_cache if tor else None
    if not tor:
        _tor_cache = None
        return None
    try:
        s = requests.Session()
        s.proxies = {"http": "socks5h://127.0.0.1:9050", "https": "socks5h://127.0.0.1:9050"}
        s.get("http://httpbin.org/ip", timeout=3)
        _tor_cache = {"http": "socks5h://127.0.0.1:9050", "https": "socks5h://127.0.0.1:9050"}
        return _tor_cache
    except Exception:
        _tor_cache = None
        return None


def search_duckduckgo(query, stop, pause, user_agent, tor=False):
    headers = {"User-Agent": user_agent}
    urls = []
    tor_proxies = _get_tor_proxies(tor)

    endpoints = []
    if tor_proxies:
        endpoints.append((
            "https://duckduckgogg42xjoc72x3sjasowoarfbgcmvfimaftt6twagswzczad.onion/html/",
            tor_proxies,
            "DuckDuckGo onion",
        ))
    endpoints.append((
        "https://html.duckduckgo.com/html/",
        tor_proxies,
        "DuckDuckGo (via Tor)" if tor_proxies else "DuckDuckGo",
    ))

    for base_url, proxies, label in endpoints:
        if len(urls) >= stop:
            break
        params = {"q": query}
        print(f"[*]   Using {label}")
        consecutive_empty = 0
        while len(urls) < stop:
            try:
                resp = requests.get(
                    base_url,
                    params=params,
                    headers=headers,
                    proxies=proxies,
                    timeout=15,
                )
                if resp.status_code != 200:
                    break

                soup = BeautifulSoup(resp.text, "html.parser")
                links = soup.select("a.result__a")

                if not links:
                    break

                before = len(urls)
                for a in links:
                    href = a.get("href")
                    if href:
                        parsed = urllib.parse.urlparse(href)
                        qs = urllib.parse.parse_qs(parsed.query)
                        actual = qs.get("uddg", [None])[0]
                        if actual and actual not in urls:
                            urls.append(actual)
                            if len(urls) >= stop:
                                break

                if len(urls) == before:
                    consecutive_empty += 1
                    if consecutive_empty >= 3:
                        break
                else:
                    consecutive_empty = 0

                params["s"] = str(int(params.get("s", "0")) + 50)
                if len(urls) > before:
                    time.sleep(pause)

            except requests.exceptions.RequestException as e:
                print(f"[-] DuckDuckGo ({label}) request error: {e}")
                break

    return urls


def search_startpage(query, stop, pause, user_agent, tor=False):
    headers = {"User-Agent": user_agent}
    urls = []
    tor_proxies = _get_tor_proxies(tor)

    endpoints = []
    if tor_proxies:
        endpoints.append((
            "http://startpagel6srwcjlue4zgq3zevrujfaow726kjytqbbjyrswwmjzcqd.onion/sp/search",
            tor_proxies,
            "Startpage onion",
        ))
    endpoints.append((
        "https://www.startpage.com/sp/search",
        tor_proxies,
        "Startpage (via Tor)" if tor_proxies else "Startpage",
    ))

    skip_domains = {"startpage.com", "startmail.com", "twitter.com", "reddit.com",
                     "instagram.com", "facebook.com", "mastodon.social"}

    for base_url, proxies, label in endpoints:
        if len(urls) >= stop:
            break
        params = {"q": query}
        print(f"[*]   Using {label}")
        consecutive_empty = 0
        while len(urls) < stop:
            try:
                resp = requests.get(
                    base_url,
                    params=params,
                    headers=headers,
                    proxies=proxies,
                    timeout=30,
                )
                if resp.status_code != 200:
                    break

                soup = BeautifulSoup(resp.text, "html.parser")

                links = (
                    soup.select("a.result-title")
                    or soup.select(".search-item__title a")
                    or soup.select("a.wgl-link")
                    or [a for a in soup.find_all("a", href=True)
                        if "/sp/view?" in a["href"]]
                )

                if not links:
                    break

                before = len(urls)
                for a in links:
                    href = a.get("href")
                    if not href:
                        continue
                    if "/sp/view?" in href:
                        parsed = urllib.parse.urlparse(href)
                        qs = urllib.parse.parse_qs(parsed.query)
                        actual = qs.get("url", [None])[0]
                        if actual:
                            href = actual
                    if href.startswith("http"):
                        domain = urllib.parse.urlparse(href).netloc.lower()
                        if domain in skip_domains or any(d in domain for d in skip_domains):
                            continue
                        if domain.endswith(".onion"):
                            continue
                        if href not in urls:
                            urls.append(href)
                            if len(urls) >= stop:
                                break

                if len(urls) == before:
                    consecutive_empty += 1
                    if consecutive_empty >= 3:
                        break
                else:
                    consecutive_empty = 0

                params["page"] = str(int(params.get("page", "1")) + 1)
                if len(urls) > before:
                    time.sleep(pause)

            except requests.exceptions.RequestException as e:
                print(f"[-] Startpage ({label}) request error: {e}")
                break

    return urls


def get_timestamp():
    now = time.localtime()
    timestamp = time.strftime("%Y%m%d_%H%M%S", now)
    return timestamp


def csv_list(string):
    return string.split(",")


# http://stackoverflow.com/questions/3853722/python-argparse-how-to-insert-newline-in-the-help-text
class SmartFormatter(argparse.HelpFormatter):
    def _split_lines(self, text, width):
        if text.startswith("R|"):
            return text[2:].splitlines()
        # This is the RawTextHelpFormatter._split_lines
        return argparse.HelpFormatter._split_lines(self, text, width)


def positive_int(value):
    try:
        value_int = int(value)
        assert value_int >= 0
        return value_int
    except (AssertionError, ValueError):
        raise argparse.ArgumentTypeError(f"invalid value '{value}', must be an int >= 0")


def positive_float(value):
    try:
        value_float = float(value)
        assert value_float >= 0
        return value_float
    except (AssertionError, ValueError):
        raise argparse.ArgumentTypeError(f"invalid value '{value}', must be a float >= 0")


def main():
    parser = argparse.ArgumentParser(
        description=f"Metagoofil v{__version__} - Search Google, DuckDuckGo, Startpage, SearXNG, MetaGer, and Mojeek and download specific file types.",
        formatter_class=SmartFormatter,
    )
    parser.add_argument(
        "-d",
        dest="domain",
        action="store",
        required=True,
        help="Domain to search.",
    )
    parser.add_argument(
        "-e",
        dest="delay",
        action="store",
        type=positive_float,
        default=30.0,
        help=(
            "Delay (in seconds) between searches. If it's too small Google may block your IP, too big and your search "
            "may take a while. Default: 30.0"
        ),
    )
    parser.add_argument(
        "-f",
        nargs="?",
        metavar="SAVE_FILE",
        dest="save_links",
        action="store",
        default=False,
        help="R|Save the html links to a file.\n"
        "no -f = Do not save links\n"
        "-f = Save links to html_links_<TIMESTAMP>.txt\n"
        "-f SAVE_FILE = Save links to SAVE_FILE",
    )
    parser.add_argument(
        "-i",
        dest="url_timeout",
        action="store",
        type=positive_int,
        default=15,
        help="Number of seconds to wait before timeout for unreachable/stale pages. Default: 15",
    )
    parser.add_argument(
        "-l",
        dest="search_max",
        action="store",
        type=positive_int,
        default=100,
        help="Maximum results to search. Default: 100",
    )
    parser.add_argument(
        "-n",
        dest="download_file_limit",
        action="store",
        type=positive_int,
        default=100,
        help="Maximum number of files to download per filetype. Default: 100",
    )
    parser.add_argument(
        "-o",
        dest="save_directory",
        action="store",
        default="./data",
        help='Directory to save downloaded files. Default is "./data"',
    )
    parser.add_argument(
        "-r",
        dest="number_of_threads",
        action="store",
        type=positive_int,
        default=8,
        help="Number of downloader threads. Default: 8",
    )
    parser.add_argument(
        "-s",
        dest="search_engines",
        action="store",
        type=csv_list,
        default=["google", "duckduckgo", "startpage", "searxng", "metager", "mojeek"],
        help="Comma-separated search engines: google,duckduckgo,startpage,searxng,metager,mojeek (default: all)",
    )
    parser.add_argument(
        "-t",
        dest="file_types",
        action="store",
        type=csv_list,
        required=True,
        help=(
            "file_types to download (pdf,doc,xls,ppt,odp,ods,docx,xlsx,pptx). To search all 17,576 three-letter "
            'file extensions, type "ALL"'
        ),
    )
    parser.add_argument(
        "-u",
        dest="user_agent",
        nargs="?",
        default=None,
        help="R|User-Agent for search engines and file retrieval against -d domain.\n"
        "no -u = Randomize User-Agent (recommended)\n"
        '-u "My custom user agent 2.0" = Your customized User-Agent',
    )
    parser.add_argument(
        "-w",
        dest="download_files",
        action="store_true",
        default=False,
        help="Download the files, instead of just viewing search results.",
    )
    parser.add_argument(
        "--tor",
        dest="tor",
        action="store_true",
        default=False,
        help="Route all search engine requests through Tor SOCKS proxy (127.0.0.1:9050). Also enables onion service endpoints for DuckDuckGo and Startpage.",
    )
    args = parser.parse_args()

    # Validate search engines
    valid_engines = {"google", "duckduckgo", "startpage", "searxng", "metager", "mojeek"}
    for e in args.search_engines:
        if e not in valid_engines:
            print(f"[-] Invalid search engine '{e}'. Valid options: {', '.join(sorted(valid_engines))}")
            sys.exit(1)

    if args.save_directory and args.download_files:
        print(f"[*] Downloaded files will be saved here: {args.save_directory}")
        if not os.path.exists(args.save_directory):
            print(f"[-] The {args.save_directory} directory does not exist...exiting.")
            sys.exit(1)

    if args.save_links is False:
        args.save_links = None
    elif args.save_links is None:
        args.save_links = f"html_links_{get_timestamp()}.txt"

    # print(vars(args))
    mg = Metagoofil(**vars(args))
    mg.go()

    print("[+] Done!")


if __name__ == "__main__":
    main()
