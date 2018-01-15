import asyncore
import asynchat

import socket
import multiprocessing
import logging
import mimetypes
import os
import urllib
import argparse
import time
import re
from urllib import parse



def url_normalize(path):
    if path.startswith("."):
        path = "/" + path
    while "../" in path:
        p1 = path.find("/..")
        p2 = path.rfind("/", 0, p1)
        if p2 != -1:
            path = path[:p2] + path[p1 + 3:]
        else:
            path = path.replace("/..", "", 1)
    path = path.replace("/./", "/")
    path = path.replace("/.", "")
    return path


class FileProducer(object):
    def __init__(self, file, chunk_size=4096):
        self.file = file
        self.chunk_size = chunk_size

    def more(self):
        if self.file:
            print("in if self.file")
            data = self.file.read(self.chunk_size)
            print(data)
            if data:
                print("in if data")
                return data
            self.file.close()
            self.file = None
        return ""


class AsyncHTTPServer(asyncore.dispatcher):
    def __init__(self, host="127.0.0.1", port=9000):
        super().__init__()
        self.create_socket()
        self.set_reuse_addr()
        self.bind((host, port))
        self.listen(5)

    def handle_accepted(self, sock, addr):
        print("Incoming connection from" + str(addr))
        AsyncHTTPRequestHandler(sock)

    def serve_forever(self):
        asyncore.loop()


class AsyncHTTPRequestHandler(asynchat.async_chat):
    def __init__(self, sock):
        super().__init__(sock)
        self.set_terminator(b"\r\n\r\n")
        self.term = "\r\n"
        self.headers = {}
        self.response_headers = {
            'Host': '127.0.0.1',
            'Server': 'ServerName',
            'Date': self.date_time_string(),
        }

        self.protocol_version = '1.1'
        self.reading_headers = False

        self.text_types = ('txt', 'html', 'css', 'js')
        self.image_types = ('jpg', 'jpeg', 'png', 'gif')

        self.responses = {
            200: ('OK', 'Request fulfilled, document follows'),
            400: ('Bad Request',
                  'Bad request syntax or unsupported method'),
            403: ('Forbidden',
                  'Request forbidden -- authorization will not help'),
            404: ('Not Found', 'Nothing matches the given URI'),
            405: ('Method Not Allowed',
                  'Specified method is invalid for this resource.'),
        }

    def collect_incoming_data(self, data):
        print("Incoming data: " + str(data))
        self._collect_incoming_data(data)

    def found_terminator(self):
        self.parse_request()

    def parse_request(self):
        if not self.reading_headers:  # Если заголовки не разобраны:
            if not self.parse_headers():  # Разобрать заголовки (parse_headers())
                #       Если заголовки сформированы неверно:
                self.send_error(400, self.responses[400])  # =Послать ответ: "400 Bad Request"
                self.handle_close()
            if self.method == 'POST':  # Если это POST-запрос:
                content_len = self.headers.get("Content-Length", 0)
                if content_len > 0:  # Если тело запроса не пустое (Content-Length > 0):
                    self.set_terminator(int(content_len))  # Дочитать запрос
                else:  # Иначе:
                    # self.body = ""
                    self.handle_request()  # Вызвать обработчик запроса (handle_request())
            else:  # Иначе:
                self.set_terminator(None)
                self.handle_request()  # Вызвать обработчик запроса (handle_request())
        else:  # Иначе:
            self.set_terminator(None)
            self.request_body = self._get_data()  # Получить тело запроса (может быть пустым)
            self.handle_request()  # Вызвать обработчик запроса (handle_request())

    def parse_headers(self):
        def make_dict(headers):
            result = {}
            for header in headers:
                key = header.split(':')[0].lower()
                value = header[len(key) + 2:]  # Host + : + ' ' = len() + 2
                result[key] = value
            return result

        raw = self._get_data().decode()

        self.method = re.findall('^[A-Z]+', raw)[0] # Парсим метод
        print('Method: ' + self.method)
        if not hasattr(self, 'do_' + self.method):
            self.send_error(405)
            return False

        matches = re.findall('\/(1.1|1.0|0.9)\\r\\n', raw) # Парсим версию протокола
        if len(matches) == 0:
            return False
        self.protocol_version = matches[0].strip().replace('/', '')
        print("protocol: " + self.protocol_version)

        expression = '^' + self.method + '(.*?)HTTP/' + self.protocol_version # Парсим uri запроса
        matches = re.findall(expression, raw)
        if len(matches) == 0:
            return False
        uri = matches[0]
        self.uri = uri[1:-1]
        self.uri = parse.unquote(self.uri)  # URLDecode
        self.uri = self.edit_path(self.uri)
        print("uri: '" + self.uri + "'")

        # Разбираем зголовки

        if self.method in ('GET', 'HEAD'):
            # 'GET / HTTP/1.1\r\nHost: 127.0.0.1:9000\r\nUser-Agent: curl/7.49.1\r\nAccept: */*'
            self.headers = make_dict(raw.split(self.term)[1:])

            if self.protocol_version == '1.1' and 'host' not in self.headers:
                return False

            # Если же у нас есть переменные в запросе
            if '?' in self.uri:
                temp = self.uri
                self.uri = re.findall('^(.*?)\?', temp)[0]
                self.query_string = temp[len(self.uri) + 1:]
                print("uri: '" + self.uri + "', query_string: '" + self.query_string + "'")

        elif self.method == 'POST':
            # 'GET / HTTP/1.1\r\nHost: 127.0.0.1:9000\r\nUser-Agent: curl/7.49.1\r\nAccept: */*\r\n\r\nBodddyyyy\r\n\r\n'
            head = raw.split(self.term * 2)[:1][0]
            self.headers = make_dict(head.split(self.term)[1:])

            if 'content-length' not in self.headers:
                return False

        return True

    def handle_request(self):
        method_name = 'do_' + self.method
        if not hasattr(self, method_name):
            self.send_error(405)
            self.handle_close()
            return
        handler = getattr(self, method_name)
        handler()

    def send_error(self, code, message=None):
        try:
            short_msg, long_msg = self.responses[code]
        except KeyError:
            short_msg, long_msg = 'error', 'Error'
        if message is None:
            message = short_msg

        self.send_response(code, message)
        self.send_header("Content-Type", "text/plain")
        self.send_header("Connection", "close")
        self.end_headers()

    def end_headers(self):
        self.push(bytes(str("\r\n"), 'utf-8'))

    def send_response(self, code, content=''):

        print("respond with code: " + str(code))

        try:
            message, _ = self.responses[code]
        except KeyError:
            message = 'WTF????'

        self.push(self.get_bytes("HTTP/" + self.protocol_version + " " + str(code) + " " + message))
        self.add_terminator()

        for key, value in self.response_headers.items():
            self.send_header(key.title(), value)
        self.add_terminator()

        if self.method == "POST":
            self.push(self.get_bytes(self.body))
        else:
            if len(content) > 0:
                if self.first_part == "image":
                    self.send(content)
                else:
                    self.push(self.get_bytes(content))

        self.add_terminator()
        self.add_terminator()
        self.handle_close()

    def date_time_string(self):
        return time.strftime("%a, %d %b %Y %H:%M:%S GMT", time.gmtime())

    def send_header(self, keyword, value):
        self.push(self.get_bytes(str(keyword) + ": " + str(value)))
        self.add_terminator()

    def add_terminator(self):
        self.push(self.get_bytes(self.term))

    def do_GET(self, without_content=False):
        print("do_GET: uri == '" + self.uri + "'")

        valid_extensions = self.text_types + self.image_types
        max_extension_length = len(max(valid_extensions, key=len)) + 1

        is_file = '.' in self.uri[-max_extension_length:]

        if not is_file:
            self.send_error(403)
            return

        if os.path.exists(self.uri):
            extension = self.uri.split(".")[-1:][0]
            if extension in valid_extensions:
                self.response_headers['content-type'] = self.make_content_type_header(extension)
                print(self.response_headers['content-type'])
                reading_mode = 'r' if extension in self.text_types else 'rb'
                with open(self.uri, reading_mode) as f:
                    data = f.read()
                    self.response_headers['content-length'] = len(data)


                if without_content:  # Если метод HEAD
                    data = ''
                self.send_error(200, data)
            else:
                self.send_error(415)
        else:
            self.send_error(404)

    def convert_extension_to_content_type_ending(self, s):
        replacements = [('txt', 'plain'), ('js', 'javascript'), ('jpg', 'jpeg')]
        for item in replacements:
            s = s.replace(item[0], item[1])
        return s

    def make_content_type_header(self, extension):
        self.first_part = 'text' if extension in self.text_types else 'image'
        extension = self.convert_extension_to_content_type_ending(extension)
        return str(self.first_part) + "/" + str(extension)

    def handle_data(self):
        f = self.send_head()
        if f:
            self.copyfile(f, self.wfile)

    def do_POST(self):
        if self.uri.endswith('.html'):

            self.send_error(400)
        else:
            self.response_headers['content-length'] = len(self.body)
            self.send_error(200)

    def do_HEAD(self):
        self.do_GET(without_content=True)

    def edit_path(self, path):
        if path.startswith("."):
            path = "/" + path
        while "../" in path:
            p1 = path.find("/..")
            p2 = path.find("/", 0, p1)
            if p2 != -1:
                path = path[:p2] + path[p1 + 3:]
            else:
                path = path.replace("/..", "", 1)
        path = path.replace("/./", "/")
        path = path.replace("/.", "")

        if path == '/':
            path += 'index.html'
        if path.startswith('/'):
            path = path[1:]
        return path


    def get_bytes(self, s):
        return bytes(str(s), 'utf-8')


def parse_args():
    parser = argparse.ArgumentParser("Simple asynchronous web-server")
    parser.add_argument("--host", dest="host", default="127.0.0.1")
    parser.add_argument("--port", dest="port", type=int, default=9000)
    parser.add_argument("--log", dest="loglevel", default="info")
    parser.add_argument("--logfile", dest="logfile", default=None)
    parser.add_argument("-w", dest="nworkers", type=int, default=1)
    parser.add_argument("-r", dest="document_root", default=".")
    return parser.parse_args()


def run():
    server = AsyncHTTPServer(host="127.0.0.1", port=9000)
    server.serve_forever()


if __name__ == "__main__":
    args = parse_args()

    logging.basicConfig(
        filename=args.logfile,
        level=getattr(logging, args.loglevel.upper()),
        format="%(name)s: %(process)d %(message)s")
    log = logging.getLogger(__name__)

    DOCUMENT_ROOT = args.document_root
    for _ in range(args.nworkers):
        p = multiprocessing.Process(target=run)
        p.start()



        # server = AsyncHTTPServer()
        # asyncore.loop()
