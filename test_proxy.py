#!/usr/bin/python

'''Test proxy web server.'''

import BaseHTTPServer, select, socket, SocketServer, urlparse
import logging
import logging.handlers
import getopt
import sys
import signal
import threading
from types import FrameType, CodeType
from time import sleep

DEFAULT_LOG_FILENAME = "proxy.log"
HOSTNAME = 'localhost'
PROXY_HOSTNAME = 'justdropt.com'
PORT = 3128
FORWARD_HOSTNAME = 'localhost'
FORWARD_PORT = 8080

class ProxyHandler(BaseHTTPServer.BaseHTTPRequestHandler):
  __base = BaseHTTPServer.BaseHTTPRequestHandler
  __base_handle = __base.handle

  def handle(self):
    (ip, port) = self.client_address
    self.server.logger.log(logging.INFO, "Request from '%s'", ip)
    if hasattr(self, 'allowed_clients') and ip not in self.allowed_clients:
      self.raw_requestline = self.rfile.readline()
      if self.parse_request(): self.send_error(403)
    else:
      self.__base_handle()

  def _connect_to(self, soc):
    host_port =(FORWARD_HOSTNAME, FORWARD_PORT)
    self.server.logger.log(logging.INFO, "connect to %s:%d", host_port[0], host_port[1])
    try:
      soc.connect(host_port)
    except socket.error, arg:
      try:
        msg = arg[1]
      except:
        msg = arg
      self.send_error(404, msg)
      return 0
    return 1

  def output_proxy(self):
    # send requests to google apps domain to direct
    self.wfile.write('''
    function FindProxyForURL(url, host) {
      if (shExpMatch(url,"*mail.%s*"))
        return "DIRECT";
      if (shExpMatch(host,"*mail.%s*"))
        return "DIRECT";
      if (shExpMatch(url,"*%s*"))
        return "PROXY %s:%d";
      return "DIRECT";
    }''' % (PROXY_HOSTNAME, PROXY_HOSTNAME, HOSTNAME, PORT))
    return

  def do_GET(self):
    (scm, netloc, path, params, query, fragment) = urlparse.urlparse(
      self.path, 'http')

    if self.path == '/proxy.pac':
      return self.output_proxy()

    if scm != 'http' or fragment or not netloc:
      self.send_error(400, "bad url %s" % self.path)
      return

    message = ''
    if "Content-Length" in self.headers:
      content_length = self.headers["Content-Length"]
      print "message length: ", content_length
      if content_length > 0:
        message = self.rfile.read(int(content_length))
        print "message: ", message

    soc = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
      if self._connect_to(soc):
        self.log_request()
        soc.send("%s %s %s\r\n" %(self.command,
                                  urlparse.urlunparse(('', '', path,
                                                       params, query,
                                                       '')),
                                  self.request_version))
        self.headers['Connection'] = 'close'
        del self.headers['Proxy-Connection']
        print 'URL: %s request' % self.path   
        for key_val in self.headers.items():
          soc.send("%s: %s\r\n" % key_val)
          print '%s: %s\n' % key_val
        soc.send("\r\n%s\r\n" % message)
        self._read_write(soc)
    finally:
      soc.close()
      self.connection.close()

  def _read_write(self, soc, max_idling=20, local=False):
    iw = [self.connection, soc]
    ow = []
    count = 0
    while 1:
      count += 1
      (ins, _, exs) = select.select(iw, ow, iw, 1)
      if exs:
        break
      if ins:
        for i in ins:
          if i is soc:
            out = self.connection
          else:
            out = soc
          data = i.recv(8192)
          if data:
            out.send(data)
            count = 0
      if count == max_idling: break

  do_HEAD = do_GET
  do_POST = do_GET
  do_PUT  = do_GET
  do_DELETE=do_GET

  def log_message(self, format, *args):
    self.server.logger.log(logging.INFO, "%s %s", self.address_string(),
                format % args)
    
  def log_error(self, format, *args):
    self.server.logger.log(logging.ERROR, "%s %s", self.address_string(),
                format % args)

class ThreadingHTTPServer(SocketServer.ThreadingMixIn,
               BaseHTTPServer.HTTPServer):
  def __init__(self, server_address, RequestHandlerClass, logger=None):
    BaseHTTPServer.HTTPServer.__init__(self, server_address,
                      RequestHandlerClass)
    self.logger = logger

def logSetup():
  logger = logging.getLogger("TinyHTTPProxy")
  logger.setLevel(logging.INFO)
  handler = logging.StreamHandler()
  fmt = logging.Formatter("[%(asctime)-12s.%(msecs)03d] "
               "%(levelname)-8s {%(name)s %(threadName)s}"
               " %(message)s",
               "%Y-%m-%d %H:%M:%S")
  handler.setFormatter(fmt)
    
  logger.addHandler(handler)
  return logger

def usage(msg=None):
  if msg: print msg
  print sys.argv[0], "[-p port] [-l logfile] [-dh] [allowed_client_name ...]]"
  print
  print "   -p     - Port to bind to"
  print

def handler(signo, frame):
  while frame and isinstance(frame, FrameType):
    if frame.f_code and isinstance(frame.f_code, CodeType):
      if "exit_event" in frame.f_code.co_varnames:
        frame.f_locals["exit_event"].set()
        return
    frame = frame.f_back
  
def main():
  logfile = None
  PORT = 3128
  exit_event = threading.Event()

  
  try: opts, args = getopt.getopt(sys.argv[1:], "l:dhp:", [])
  except getopt.GetoptError, e:
    usage(str(e))
    return 1

  for opt, value in opts:
    # TODO: add support for the forward host and port through the command line
    if opt == "-p":
      port = int(value)
    else:
      usage()
      return 0
    
  # setup the log file
  logger = logSetup()
  
  signal.signal(signal.SIGINT, handler)

  server_address = (HOSTNAME, PORT)
  ProxyHandler.protocol = "HTTP/1.0"
  httpd = ThreadingHTTPServer(server_address, ProxyHandler, logger)
  sa = httpd.socket.getsockname()
  print "Servering HTTP on", sa[0], "port", sa[1]
  req_count = 0
  while not exit_event.isSet():
    try:
      httpd.handle_request()
      req_count += 1
      if req_count == 1000:
        logger.log(logging.INFO, "Number of active threads: %s",
              threading.activeCount())
        req_count = 0
    except select.error, e:
      if e[0] == 4 and exit_event.isSet(): pass
      else:
        logger.log(logging.CRITICAL, "Errno: %d - %s", e[0], e[1])
  logger.log(logging.INFO, "Server shutdown")
  return 0

if __name__ == '__main__':
  sys.exit(main())

