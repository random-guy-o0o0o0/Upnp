# Please paste the original UPnP / DLNA Media Server code here.
"""
Offline UPnP / DLNA Media & Web File Server
Pure Python 3 - Zero external dependencies.
Runs on Windows, macOS, Linux, Android (Termux), iOS (iSH/Pythonista).
"""

import os
import sys
import socket
import struct
import threading
import mimetypes
import time
import urllib.parse
from http.server import HTTPServer, BaseHTTPRequestHandler
from xml.sax.saxutils import escape

SSDP_ADDR = "239.255.255.250"
SSDP_PORT = 1900
DEFAULT_HTTP_PORT = 8000
SERVER_UUID = "uuid:5b9671d4-8149-4bc2-89f4-184cf43d7890"

# Register common media mime types
mimetypes.add_type("video/mp4", ".mp4")
mimetypes.add_type("video/x-matroska", ".mkv")
mimetypes.add_type("video/webm", ".webm")
mimetypes.add_type("video/quicktime", ".mov")
mimetypes.add_type("audio/mpeg", ".mp3")
mimetypes.add_type("audio/flac", ".flac")
mimetypes.add_type("audio/ogg", ".ogg")
mimetypes.add_type("audio/wav", ".wav")
mimetypes.add_type("audio/aac", ".aac")
mimetypes.add_type("image/jpeg", ".jpg")
mimetypes.add_type("image/jpeg", ".jpeg")
mimetypes.add_type("image/png", ".png")
mimetypes.add_type("image/webp", ".webp")
mimetypes.add_type("application/pdf", ".pdf")


def get_local_ip():
    """Detect the local IP address on the current network interface."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(('10.255.255.255', 1))
        ip = s.getsockname()[0]
    except Exception:
        try:
            ip = socket.gethostbyname(socket.gethostname())
        except Exception:
            ip = "127.0.0.1"
    finally:
        s.close()
    return ip


def format_size(bytes_val):
    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
        if bytes_val < 1024:
            return f"{bytes_val:.1f} {unit}"
        bytes_val /= 1024
    return f"{bytes_val:.1f} PB"


class UPnPServerContext:
    def __init__(self, host_ip, http_port, media_root, server_name="Offline Media Server"):
        self.host_ip = host_ip
        self.http_port = http_port
        self.media_root = os.path.abspath(media_root)
        self.server_name = server_name
        self.base_url = f"http://{host_ip}:{http_port}"


class UPnPRequestHandler(BaseHTTPRequestHandler):
    server_version = "OfflineUPnP/1.0"

    def log_message(self, format, *args):
        # Keep terminal output clean
        sys.stderr.write(f"[{self.log_date_time_string()}] {format % args}\n")

    def context(self) -> UPnPServerContext:
        return self.server.context

    def do_GET(self):
        url = urllib.parse.urlparse(self.path)
        path = urllib.parse.unquote(url.path)

        if path in ["", "/"]:
            self.serve_web_ui()
        elif path == "/description.xml":
            self.serve_description_xml()
        elif path == "/content_directory.xml":
            self.serve_content_directory_scpd()
        elif path == "/connection_manager.xml":
            self.serve_connection_manager_scpd()
        elif path.startswith("/media/"):
            rel_path = path[len("/media/"):]
            self.serve_media_file(rel_path)
        elif path.startswith("/download/"):
            rel_path = path[len("/download/"):]
            self.serve_media_file(rel_path, as_attachment=True)
        else:
            self.send_error(404, "Not Found")

    def do_POST(self):
        url = urllib.parse.urlparse(self.path)
        path = urllib.parse.unquote(url.path)

        if path == "/control/ContentDirectory":
            self.handle_soap_content_directory()
        elif path == "/control/ConnectionManager":
            self.handle_soap_connection_manager()
        elif path == "/upload":
            self.handle_web_upload()
        else:
            self.send_error(404, "Not Found")

    # -------------------------------------------------------------
    # UPnP Device Description & SCPD
    # -------------------------------------------------------------
    def serve_description_xml(self):
        ctx = self.context()
        xml = f"""<?xml version="1.0" encoding="utf-8"?>
<root xmlns="urn:schemas-upnp-org:device-1-0">
  <specVersion>
    <major>1</major>
    <minor>0</minor>
  </specVersion>
  <device>
    <deviceType>urn:schemas-upnp-org:device:MediaServer:1</deviceType>
    <friendlyName>{escape(ctx.server_name)} ({ctx.host_ip})</friendlyName>
    <manufacturer>Offline Universal</manufacturer>
    <manufacturerURL>{ctx.base_url}</manufacturerURL>
    <modelDescription>Offline UPnP/DLNA Media &amp; File Server</modelDescription>
    <modelName>OfflineMediaServer</modelName>
    <modelNumber>1.0</modelNumber>
    <UDN>{SERVER_UUID}</UDN>
    <serviceList>
      <service>
        <serviceType>urn:schemas-upnp-org:service:ContentDirectory:1</serviceType>
        <serviceId>urn:upnp-org:serviceId:ContentDirectory</serviceId>
        <SCPDURL>/content_directory.xml</SCPDURL>
        <controlURL>/control/ContentDirectory</controlURL>
        <eventSubURL>/events/ContentDirectory</eventSubURL>
      </service>
      <service>
        <serviceType>urn:schemas-upnp-org:service:ConnectionManager:1</serviceType>
        <serviceId>urn:upnp-org:serviceId:ConnectionManager</serviceId>
        <SCPDURL>/connection_manager.xml</SCPDURL>
        <controlURL>/control/ConnectionManager</controlURL>
        <eventSubURL>/events/ConnectionManager</eventSubURL>
      </service>
    </serviceList>
  </device>
</root>"""
        data = xml.encode('utf-8')
        self.send_response(200)
        self.send_header("Content-Type", "text/xml; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(data)

    def serve_content_directory_scpd(self):
        xml = """<?xml version="1.0" encoding="utf-8"?>
<scpd xmlns="urn:schemas-upnp-org:service-1-0">
  <specVersion><major>1</major><minor>0</minor></specVersion>
  <actionList>
    <action>
      <name>GetSearchCapabilities</name>
      <argumentList>
        <argument><name>SearchCaps</name><direction>out</direction><relatedStateVariable>SearchCapabilities</relatedStateVariable></argument>
      </argumentList>
    </action>
    <action>
      <name>GetSortCapabilities</name>
      <argumentList>
        <argument><name>SortCaps</name><direction>out</direction><relatedStateVariable>SortCapabilities</relatedStateVariable></argument>
      </argumentList>
    </action>
    <action>
      <name>GetSystemUpdateID</name>
      <argumentList>
        <argument><name>Id</name><direction>out</direction><relatedStateVariable>SystemUpdateID</relatedStateVariable></argument>
      </argumentList>
    </action>
    <action>
      <name>Browse</name>
      <argumentList>
        <argument><name>ObjectID</name><direction>in</direction><relatedStateVariable>A_ARG_TYPE_ObjectID</relatedStateVariable></argument>
        <argument><name>BrowseFlag</name><direction>in</direction><relatedStateVariable>A_ARG_TYPE_BrowseFlag</relatedStateVariable></argument>
        <argument><name>Filter</name><direction>in</direction><relatedStateVariable>A_ARG_TYPE_Filter</relatedStateVariable></argument>
        <argument><name>StartingIndex</name><direction>in</direction><relatedStateVariable>A_ARG_TYPE_Index</relatedStateVariable></argument>
        <argument><name>RequestedCount</name><direction>in</direction><relatedStateVariable>A_ARG_TYPE_Count</relatedStateVariable></argument>
        <argument><name>SortCriteria</name><direction>in</direction><relatedStateVariable>A_ARG_TYPE_SortCriteria</relatedStateVariable></argument>
        <argument><name>Result</name><direction>out</direction><relatedStateVariable>A_ARG_TYPE_Result</relatedStateVariable></argument>
        <argument><name>NumberReturned</name><direction>out</direction><relatedStateVariable>A_ARG_TYPE_Count</relatedStateVariable></argument>
        <argument><name>TotalMatches</name><direction>out</direction><relatedStateVariable>A_ARG_TYPE_Count</relatedStateVariable></argument>
        <argument><name>UpdateID</name><direction>out</direction><relatedStateVariable>SystemUpdateID</relatedStateVariable></argument>
      </argumentList>
    </action>
  </actionList>
  <serviceStateTable>
    <stateVariable sendEvents="no"><name>A_ARG_TYPE_ObjectID</name><dataType>string</dataType></stateVariable>
    <stateVariable sendEvents="no"><name>A_ARG_TYPE_Result</name><dataType>string</dataType></stateVariable>
    <stateVariable sendEvents="no"><name>SearchCapabilities</name><dataType>string</dataType></stateVariable>
    <stateVariable sendEvents="no"><name>SortCapabilities</name><dataType>string</dataType></stateVariable>
    <stateVariable sendEvents="yes"><name>SystemUpdateID</name><dataType>ui4</dataType></stateVariable>
    <stateVariable sendEvents="no"><name>A_ARG_TYPE_Count</name><dataType>ui4</dataType></stateVariable>
    <stateVariable sendEvents="no"><name>A_ARG_TYPE_Index</name><dataType>ui4</dataType></stateVariable>
    <stateVariable sendEvents="no"><name>A_ARG_TYPE_BrowseFlag</name><dataType>string</dataType><allowedValueList><allowedValue>BrowseMetadata</allowedValue><allowedValue>BrowseDirectChildren</allowedValue></allowedValueList></stateVariable>
    <stateVariable sendEvents="no"><name>A_ARG_TYPE_Filter</name><dataType>string</dataType></stateVariable>
    <stateVariable sendEvents="no"><name>A_ARG_TYPE_SortCriteria</name><dataType>string</dataType></stateVariable>
  </serviceStateTable>
</scpd>"""
        data = xml.encode('utf-8')
        self.send_response(200)
        self.send_header("Content-Type", "text/xml; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def serve_connection_manager_scpd(self):
        xml = """<?xml version="1.0" encoding="utf-8"?>
<scpd xmlns="urn:schemas-upnp-org:service-1-0">
  <specVersion><major>1</major><minor>0</minor></specVersion>
  <actionList>
    <action>
      <name>GetProtocolInfo</name>
      <argumentList>
        <argument><name>Source</name><direction>out</direction><relatedStateVariable>SourceProtocolInfo</relatedStateVariable></argument>
        <argument><name>Sink</name><direction>out</direction><relatedStateVariable>SinkProtocolInfo</relatedStateVariable></argument>
      </argumentList>
    </action>
  </actionList>
  <serviceStateTable>
    <stateVariable sendEvents="yes"><name>SourceProtocolInfo</name><dataType>string</dataType></stateVariable>
    <stateVariable sendEvents="no"><name>SinkProtocolInfo</name><dataType>string</dataType></stateVariable>
  </serviceStateTable>
</scpd>"""
        data = xml.encode('utf-8')
        self.send_response(200)
        self.send_header("Content-Type", "text/xml; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    # -------------------------------------------------------------
    # SOAP Handlers
    # -------------------------------------------------------------
    def handle_soap_connection_manager(self):
        content_len = int(self.headers.get("Content-Length", 0))
        _ = self.rfile.read(content_len) if content_len > 0 else b""

        soap_resp = """<?xml version="1.0" encoding="utf-8"?>
<s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/" s:encodingStyle="http://schemas.xmlsoap.org/soap/encoding/">
  <s:Body>
    <u:GetProtocolInfoResponse xmlns:u="urn:schemas-upnp-org:service:ConnectionManager:1">
      <Source>http-get:*:*:*</Source>
      <Sink></Sink>
    </u:GetProtocolInfoResponse>
  </s:Body>
</s:Envelope>"""
        data = soap_resp.encode('utf-8')
        self.send_response(200)
        self.send_header("Content-Type", 'text/xml; charset="utf-8"')
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def handle_soap_content_directory(self):
        content_len = int(self.headers.get("Content-Length", 0))
        post_data = self.rfile.read(content_len).decode('utf-8', errors='ignore') if content_len > 0 else ""
        soap_action = self.headers.get("SOAPACTION", "")

        if "Browse" in soap_action or "<Browse" in post_data or ":Browse" in post_data:
            # Extract parameters
            obj_id = "0"
            if "<ObjectID>" in post_data:
                obj_id = post_data.split("<ObjectID>")[1].split("</ObjectID>")[0].strip()

            browse_flag = "BrowseDirectChildren"
            if "<BrowseFlag>" in post_data:
                browse_flag = post_data.split("<BrowseFlag>")[1].split("</BrowseFlag>")[0].strip()

            starting_index = 0
            if "<StartingIndex>" in post_data:
                try:
                    starting_index = int(post_data.split("<StartingIndex>")[1].split("</StartingIndex>")[0].strip())
                except ValueError:
                    starting_index = 0

            req_count = 0
            if "<RequestedCount>" in post_data:
                try:
                    req_count = int(post_data.split("<RequestedCount>")[1].split("</RequestedCount>")[0].strip())
                except ValueError:
                    req_count = 0

            didl, count, total = self.generate_didl_lite(obj_id, browse_flag, starting_index, req_count)

            soap_resp = f"""<?xml version="1.0" encoding="utf-8"?>
<s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/" s:encodingStyle="http://schemas.xmlsoap.org/soap/encoding/">
  <s:Body>
    <u:BrowseResponse xmlns:u="urn:schemas-upnp-org:service:ContentDirectory:1">
      <Result>{escape(didl)}</Result>
      <NumberReturned>{count}</NumberReturned>
      <TotalMatches>{total}</TotalMatches>
      <UpdateID>1</UpdateID>
    </u:BrowseResponse>
  </s:Body>
</s:Envelope>"""
            data = soap_resp.encode('utf-8')
            self.send_response(200)
            self.send_header("Content-Type", 'text/xml; charset="utf-8"')
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
        elif "GetSystemUpdateID" in soap_action or "GetSystemUpdateID" in post_data:
            soap_resp = """<?xml version="1.0" encoding="utf-8"?>
<s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/" s:encodingStyle="http://schemas.xmlsoap.org/soap/encoding/">
  <s:Body>
    <u:GetSystemUpdateIDResponse xmlns:u="urn:schemas-upnp-org:service:ContentDirectory:1">
      <Id>1</Id>
    </u:GetSystemUpdateIDResponse>
  </s:Body>
</s:Envelope>"""
            data = soap_resp.encode('utf-8')
            self.send_response(200)
            self.send_header("Content-Type", 'text/xml; charset="utf-8"')
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
        elif "GetSortCapabilities" in soap_action or "GetSortCapabilities" in post_data:
            soap_resp = """<?xml version="1.0" encoding="utf-8"?>
<s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/" s:encodingStyle="http://schemas.xmlsoap.org/soap/encoding/">
  <s:Body>
    <u:GetSortCapabilitiesResponse xmlns:u="urn:schemas-upnp-org:service:ContentDirectory:1">
      <SortCaps>dc:title</SortCaps>
    </u:GetSortCapabilitiesResponse>
  </s:Body>
</s:Envelope>"""
            data = soap_resp.encode('utf-8')
            self.send_response(200)
            self.send_header("Content-Type", 'text/xml; charset="utf-8"')
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
        else:
            self.send_error(501, "Not Implemented")

    def generate_didl_lite(self, obj_id, browse_flag, starting_index, req_count):
        ctx = self.context()
        if obj_id == "0":
            target_dir = ctx.media_root
            rel_folder = ""
        else:
            # Decode relative folder path
            rel_folder = urllib.parse.unquote(obj_id)
            target_dir = os.path.normpath(os.path.join(ctx.media_root, rel_folder))
            if not target_dir.startswith(ctx.media_root):
                target_dir = ctx.media_root
                rel_folder = ""

        didl_items = []

        if browse_flag == "BrowseMetadata":
            title = os.path.basename(target_dir) if rel_folder else ctx.server_name
            didl = f"""<DIDL-Lite xmlns="urn:schemas-upnp-org:metadata-1-0/DIDL-Lite/" xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:upnp="urn:schemas-upnp-org:metadata-1-0/upnp/">
  <container id="{escape(obj_id)}" parentID="0" restricted="1">
    <dc:title>{escape(title)}</dc:title>
    <upnp:class>object.container.storageFolder</upnp:class>
  </container>
</DIDL-Lite>"""
            return didl, 1, 1

        # BrowseDirectChildren
        if not os.path.isdir(target_dir):
            return '<DIDL-Lite xmlns="urn:schemas-upnp-org:metadata-1-0/DIDL-Lite/"></DIDL-Lite>', 0, 0

        entries = sorted(os.listdir(target_dir))
        # Separate directories and files
        dirs = [e for e in entries if os.path.isdir(os.path.join(target_dir, e)) and not e.startswith(".")]
        files = [e for e in entries if os.path.isfile(os.path.join(target_dir, e)) and not e.startswith(".")]

        all_entries = []

        for d in dirs:
            sub_rel = os.path.join(rel_folder, d) if rel_folder else d
            container_id = urllib.parse.quote(sub_rel)
            all_entries.append(
                f'<container id="{container_id}" parentID="{escape(obj_id)}" restricted="1">'
                f'<dc:title>{escape(d)}</dc:title>'
                f'<upnp:class>object.container.storageFolder</upnp:class>'
                f'</container>'
            )

        for f in files:
            file_rel = os.path.join(rel_folder, f) if rel_folder else f
            file_full = os.path.join(target_dir, f)
            try:
                f_size = os.path.getsize(file_full)
            except OSError:
                f_size = 0
            mime, _ = mimetypes.guess_type(file_full)
            mime = mime or "application/octet-stream"

            upnp_class = "object.item"
            if mime.startswith("video/"):
                upnp_class = "object.item.videoItem"
            elif mime.startswith("audio/"):
                upnp_class = "object.item.audioItem"
            elif mime.startswith("image/"):
                upnp_class = "object.item.imageItem.photo"

            item_id = urllib.parse.quote(file_rel)
            res_url = f"{ctx.base_url}/media/{urllib.parse.quote(file_rel)}"
            protocol_info = f"http-get:*:{mime}:DLNA.ORG_OP=01;DLNA.ORG_CI=0;DLNA.ORG_FLAGS=01700000000000000000000000000000"

            all_entries.append(
                f'<item id="{item_id}" parentID="{escape(obj_id)}" restricted="1">'
                f'<dc:title>{escape(f)}</dc:title>'
                f'<upnp:class>{upnp_class}</upnp:class>'
                f'<res protocolInfo="{protocol_info}" size="{f_size}">{res_url}</res>'
                f'</item>'
            )

        total = len(all_entries)
        if starting_index >= total:
            paged = []
        elif req_count > 0:
            paged = all_entries[starting_index : starting_index + req_count]
        else:
            paged = all_entries[starting_index:]

        items_xml = "".join(paged)
        didl = (
            f'<DIDL-Lite xmlns="urn:schemas-upnp-org:metadata-1-0/DIDL-Lite/" '
            f'xmlns:dc="http://purl.org/dc/elements/1.1/" '
            f'xmlns:upnp="urn:schemas-upnp-org:metadata-1-0/upnp/">'
            f'{items_xml}'
            f'</DIDL-Lite>'
        )
        return didl, len(paged), total

    # -------------------------------------------------------------
    # Media & File Streaming (with HTTP Range for Seeking)
    # -------------------------------------------------------------
    def serve_media_file(self, rel_path, as_attachment=False):
        ctx = self.context()
        clean_rel = os.path.normpath(rel_path).lstrip("/\\")
        abs_path = os.path.normpath(os.path.join(ctx.media_root, clean_rel))

        if not abs_path.startswith(ctx.media_root) or not os.path.isfile(abs_path):
            self.send_error(404, "File Not Found")
            return

        file_size = os.path.getsize(abs_path)
        mime_type, _ = mimetypes.guess_type(abs_path)
        mime_type = mime_type or "application/octet-stream"

        range_header = self.headers.get("Range")
        if range_header and range_header.startswith("bytes="):
            # Parse Range request
            try:
                ranges = range_header.split("=")[1].strip().split("-")
                start = int(ranges[0]) if ranges[0] else 0
                end = int(ranges[1]) if ranges[1] else file_size - 1
                if start >= file_size or end >= file_size or start > end:
                    self.send_response(416)
                    self.send_header("Content-Range", f"bytes */{file_size}")
                    self.end_headers()
                    return
                length = end - start + 1

                self.send_response(206)
                self.send_header("Content-Type", mime_type)
                self.send_header("Content-Range", f"bytes {start}-{end}/{file_size}")
                self.send_header("Content-Length", str(length))
                self.send_header("Accept-Ranges", "bytes")
                self.send_header("transferMode.dlna.org", "Streaming")
                self.send_header("contentFeatures.dlna.org", "DLNA.ORG_OP=01;DLNA.ORG_CI=0;DLNA.ORG_FLAGS=01700000000000000000000000000000")
                if as_attachment:
                    self.send_header("Content-Disposition", f'attachment; filename="{os.path.basename(abs_path)}"')
                self.end_headers()

                with open(abs_path, "rb") as f:
                    f.seek(start)
                    remaining = length
                    while remaining > 0:
                        chunk = f.read(min(remaining, 64 * 1024))
                        if not chunk:
                            break
                        self.wfile.write(chunk)
                        remaining -= len(chunk)
                return
            except (ConnectionResetError, BrokenPipeError):
                return
            except Exception as e:
                self.send_error(500, f"Streaming error: {e}")
                return

        # Regular Full File Delivery
        self.send_response(200)
        self.send_header("Content-Type", mime_type)
        self.send_header("Content-Length", str(file_size))
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("transferMode.dlna.org", "Streaming")
        self.send_header("contentFeatures.dlna.org", "DLNA.ORG_OP=01;DLNA.ORG_CI=0;DLNA.ORG_FLAGS=01700000000000000000000000000000")
        if as_attachment:
            self.send_header("Content-Disposition", f'attachment; filename="{os.path.basename(abs_path)}"')
        self.end_headers()

        try:
            with open(abs_path, "rb") as f:
                while True:
                    chunk = f.read(64 * 1024)
                    if not chunk:
                        break
                    self.wfile.write(chunk)
        except (ConnectionResetError, BrokenPipeError):
            pass

    # -------------------------------------------------------------
    # Responsive Offline Web Interface for Mobiles & Laptops
    # -------------------------------------------------------------
    def serve_web_ui(self):
        ctx = self.context()
        query = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
        rel_dir = query.get("dir", [""])[0]
        clean_dir = os.path.normpath(rel_dir).lstrip("/\\")
        abs_dir = os.path.normpath(os.path.join(ctx.media_root, clean_dir))

        if not abs_dir.startswith(ctx.media_root) or not os.path.isdir(abs_dir):
            abs_dir = ctx.media_root
            clean_dir = ""

        items = []
        try:
            entries = sorted(os.listdir(abs_dir))
        except OSError:
            entries = []

        dirs = [e for e in entries if os.path.isdir(os.path.join(abs_dir, e)) and not e.startswith(".")]
        files = [e for e in entries if os.path.isfile(os.path.join(abs_dir, e)) and not e.startswith(".")]

        # Breadcrumbs
        breadcrumbs_html = '<a href="/">Home</a>'
        if clean_dir:
            parts = clean_dir.split(os.sep)
            curr = ""
            for part in parts:
                curr = os.path.join(curr, part) if curr else part
                breadcrumbs_html += f' / <a href="/?dir={urllib.parse.quote(curr)}">{escape(part)}</a>'

        # Directory Rows
        dir_rows = ""
        if clean_dir:
            parent_dir = os.path.dirname(clean_dir)
            parent_link = f"/?dir={urllib.parse.quote(parent_dir)}" if parent_dir else "/"
            dir_rows += f"""<tr>
              <td>📁 <a href="{parent_link}"><strong>.. (Up one level)</strong></a></td>
              <td>Folder</td>
              <td>—</td>
              <td>—</td>
            </tr>"""

        for d in dirs:
            sub = os.path.join(clean_dir, d) if clean_dir else d
            dir_rows += f"""<tr>
              <td>📁 <a href="/?dir={urllib.parse.quote(sub)}"><strong>{escape(d)}</strong></a></td>
              <td>Folder</td>
              <td>—</td>
              <td><a href="/?dir={urllib.parse.quote(sub)}" class="btn">Open</a></td>
            </tr>"""

        file_rows = ""
        for f in files:
            f_rel = os.path.join(clean_dir, f) if clean_dir else f
            f_abs = os.path.join(abs_dir, f)
            size_str = format_size(os.path.getsize(f_abs))
            mime, _ = mimetypes.guess_type(f_abs)
            mime = mime or "File"

            encoded_rel = urllib.parse.quote(f_rel)
            stream_url = f"/media/{encoded_rel}"
            download_url = f"/download/{encoded_rel}"

            action_buttons = f'<a href="{download_url}" class="btn">Download</a>'
            icon = "📄"
            if mime.startswith("video/"):
                icon = "🎬"
                action_buttons = f'<a href="{stream_url}" target="_blank" class="btn btn-primary">Play</a> ' + action_buttons
            elif mime.startswith("audio/"):
                icon = "🎵"
                action_buttons = f'<a href="{stream_url}" target="_blank" class="btn btn-primary">Listen</a> ' + action_buttons
            elif mime.startswith("image/"):
                icon = "🖼️"
                action_buttons = f'<a href="{stream_url}" target="_blank" class="btn btn-primary">View</a> ' + action_buttons

            file_rows += f"""<tr>
              <td>{icon} <a href="{stream_url}">{escape(f)}</a></td>
              <td>{mime.split('/')[0].capitalize()}</td>
              <td>{size_str}</td>
              <td>{action_buttons}</td>
            </tr>"""

        html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{escape(ctx.server_name)}</title>
  <style>
    :root {{
      --bg: #0f172a;
      --card: #1e293b;
      --border: #334155;
      --text: #f8fafc;
      --muted: #94a3b8;
      --primary: #38bdf8;
      --primary-hover: #0284c7;
      --accent: #10b981;
    }}
    * {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
      background: var(--bg);
      color: var(--text);
      padding: 1rem;
      line-height: 1.5;
    }}
    .container {{ max-width: 960px; margin: 0 auto; }}
    header {{
      background: var(--card);
      border: 1px solid var(--border);
      border-radius: 12px;
      padding: 1.5rem;
      margin-bottom: 1.5rem;
      display: flex;
      flex-wrap: wrap;
      justify-content: space-between;
      align-items: center;
      gap: 1rem;
    }}
    .brand h1 {{ font-size: 1.5rem; color: var(--primary); }}
    .brand p {{ font-size: 0.875rem; color: var(--muted); }}
    .badge {{
      background: rgba(16, 185, 129, 0.15);
      color: var(--accent);
      padding: 0.35rem 0.75rem;
      border-radius: 9999px;
      font-size: 0.8rem;
      font-weight: 600;
      display: inline-flex;
      align-items: center;
      gap: 0.35rem;
    }}
    .badge::before {{ content: "●"; font-size: 0.75rem; }}
    .info-card {{
      background: var(--card);
      border: 1px solid var(--border);
      border-radius: 12px;
      padding: 1rem 1.25rem;
      margin-bottom: 1.5rem;
      font-size: 0.9rem;
    }}
    .info-card strong {{ color: var(--primary); }}
    .breadcrumbs {{
      margin-bottom: 1rem;
      padding: 0.5rem 0;
      color: var(--muted);
      font-size: 0.95rem;
    }}
    .breadcrumbs a {{ color: var(--primary); text-decoration: none; }}
    table {{
      width: 100%;
      border-collapse: collapse;
      background: var(--card);
      border: 1px solid var(--border);
      border-radius: 12px;
      overflow: hidden;
      margin-bottom: 1.5rem;
    }}
    th, td {{
      padding: 0.85rem 1rem;
      text-align: left;
      border-bottom: 1px solid var(--border);
    }}
    th {{ background: rgba(255,255,255,0.03); color: var(--muted); font-size: 0.8rem; text-transform: uppercase; }}
    tr:last-child td {{ border-bottom: none; }}
    tr:hover td {{ background: rgba(255,255,255,0.02); }}
    a {{ color: var(--text); text-decoration: none; }}
    a:hover {{ color: var(--primary); }}
    .btn {{
      display: inline-block;
      padding: 0.35rem 0.75rem;
      font-size: 0.8rem;
      font-weight: 600;
      border-radius: 6px;
      background: rgba(255,255,255,0.08);
      color: var(--text);
      text-decoration: none;
      transition: background 0.15s;
    }}
    .btn:hover {{ background: rgba(255,255,255,0.15); }}
    .btn-primary {{
      background: var(--primary);
      color: #0f172a;
    }}
    .btn-primary:hover {{ background: var(--primary-hover); }}
    .upload-box {{
      background: var(--card);
      border: 2px dashed var(--border);
      border-radius: 12px;
      padding: 1.5rem;
      text-align: center;
    }}
    .upload-box input[type="file"] {{ display: none; }}
    .upload-label {{
      display: inline-block;
      cursor: pointer;
      background: var(--primary);
      color: #0f172a;
      font-weight: 600;
      padding: 0.6rem 1.2rem;
      border-radius: 8px;
      margin-top: 0.5rem;
    }}
    @media (max-width: 600px) {{
      th:nth-child(2), td:nth-child(2) {{ display: none; }}
      header {{ flex-direction: column; align-items: flex-start; }}
    }}
  </style>
</head>
<body>
  <div class="container">
    <header>
      <div class="brand">
        <h1>{escape(ctx.server_name)}</h1>
        <p>Offline UPnP / DLNA &amp; Web File Sharing</p>
      </div>
      <div>
        <span class="badge">Offline Active</span>
      </div>
    </header>

    <div class="info-card">
      <p>📡 <strong>Local Access:</strong> <code>http://{ctx.host_ip}:{ctx.http_port}</code></p>
      <p>📱 <strong>Mobile Apps:</strong> Open <strong>VLC</strong>, <strong>BubbleUPnP</strong>, or <strong>Nova Video Player</strong> on your phone or laptop. It will automatically detect <em>{escape(ctx.server_name)}</em> via UPnP / DLNA!</p>
    </div>

    <div class="breadcrumbs">
      📂 Location: {breadcrumbs_html}
    </div>

    <table>
      <thead>
        <tr>
          <th>Name</th>
          <th>Type</th>
          <th>Size</th>
          <th>Actions</th>
        </tr>
      </thead>
      <tbody>
        {dir_rows}
        {file_rows if file_rows or dir_rows else '<tr><td colspan="4" style="text-align:center; color:var(--muted); padding:2rem;">This folder is empty. Upload files below!</td></tr>'}
      </tbody>
    </table>

    <div class="upload-box">
      <h3>📤 Send Files from Phone or Laptop</h3>
      <p style="color:var(--muted); font-size:0.875rem; margin-top:0.25rem;">Transfer files wirelessly without internet</p>
      <form action="/upload" method="post" enctype="multipart/form-data" style="margin-top:1rem;">
        <input type="hidden" name="dir" value="{escape(clean_dir)}">
        <label class="upload-label" for="fileInput">Choose File to Upload</label>
        <input id="fileInput" type="file" name="file" onchange="this.form.submit()">
      </form>
    </div>
  </div>
</body>
</html>"""
        data = html.encode('utf-8')
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def handle_web_upload(self):
        ctx = self.context()
        content_type = self.headers.get("Content-Type", "")
        if not content_type.startswith("multipart/form-data"):
            self.send_error(400, "Bad Request: Expected multipart/form-data")
            return

        boundary = content_type.split("boundary=")[1].encode()
        content_length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_length)

        # Parse simple multipart
        parts = body.split(b"--" + boundary)
        target_dir = ctx.media_root

        for part in parts:
            if b'name="dir"' in part:
                try:
                    dir_val = part.split(b"\r\n\r\n")[1].split(b"\r\n")[0].decode('utf-8').strip()
                    if dir_val:
                        candidate = os.path.normpath(os.path.join(ctx.media_root, dir_val))
                        if candidate.startswith(ctx.media_root) and os.path.isdir(candidate):
                            target_dir = candidate
                except Exception:
                    pass

        saved_file = False
        for part in parts:
            if b'filename="' in part:
                try:
                    headers_part, file_data = part.split(b"\r\n\r\n", 1)
                    # Remove trailing \r\n
                    if file_data.endswith(b"\r\n"):
                        file_data = file_data[:-2]

                    # Extract filename
                    fname_header = [h for h in headers_part.split(b"\r\n") if b'filename="' in h][0]
                    filename = fname_header.split(b'filename="')[1].split(b'"')[0].decode('utf-8', errors='ignore')
                    filename = os.path.basename(filename)

                    if filename:
                        save_path = os.path.join(target_dir, filename)
                        with open(save_path, "wb") as f_out:
                            f_out.write(file_data)
                        saved_file = True
                except Exception as e:
                    sys.stderr.write(f"Upload error: {e}\n")

        # Redirect back to folder
        self.send_response(303)
        rel_back = os.path.relpath(target_dir, ctx.media_root)
        redirect_url = f"/?dir={urllib.parse.quote(rel_back)}" if rel_back != "." else "/"
        self.send_header("Location", redirect_url)
        self.end_headers()


# -----------------------------------------------------------------
# SSDP Discovery Responder (UDP Multicast)
# -----------------------------------------------------------------
class SSDPResponder(threading.Thread):
    def __init__(self, host_ip, http_port, server_name="Offline UPnP Media Server"):
        super().__init__(daemon=True)
        self.host_ip = host_ip
        self.http_port = http_port
        self.server_name = server_name
        self.location = f"http://{host_ip}:{http_port}/description.xml"
        self.running = True

    def build_alive_packet(self, nt, usn):
        return (
            f"NOTIFY * HTTP/1.1\r\n"
            f"HOST: {SSDP_ADDR}:{SSDP_PORT}\r\n"
            f"CACHE-CONTROL: max-age=1800\r\n"
            f"LOCATION: {self.location}\r\n"
            f"NT: {nt}\r\n"
            f"NTS: ssdp:alive\r\n"
            f"SERVER: Python/3.11 UPnP/1.0 DLNADOC/1.50\r\n"
            f"USN: {usn}\r\n\r\n"
        ).encode('utf-8')

    def build_search_response(self, st, usn):
        return (
            f"HTTP/1.1 200 OK\r\n"
            f"CACHE-CONTROL: max-age=1800\r\n"
            f"DATE: {time.strftime('%a, %d %b %Y %H:%M:%S GMT', time.gmtime())}\r\n"
            f"EXT:\r\n"
            f"LOCATION: {self.location}\r\n"
            f"SERVER: Python/3.11 UPnP/1.0 DLNADOC/1.50\r\n"
            f"ST: {st}\r\n"
            f"USN: {usn}\r\n\r\n"
        ).encode('utf-8')

    def send_announcements(self, sock):
        targets = [
            ("upnp:rootdevice", f"{SERVER_UUID}::upnp:rootdevice"),
            (SERVER_UUID, SERVER_UUID),
            ("urn:schemas-upnp-org:device:MediaServer:1", f"{SERVER_UUID}::urn:schemas-upnp-org:device:MediaServer:1"),
            ("urn:schemas-upnp-org:service:ContentDirectory:1", f"{SERVER_UUID}::urn:schemas-upnp-org:service:ContentDirectory:1"),
            ("urn:schemas-upnp-org:service:ConnectionManager:1", f"{SERVER_UUID}::urn:schemas-upnp-org:service:ConnectionManager:1"),
        ]
        for nt, usn in targets:
            try:
                pkt = self.build_alive_packet(nt, usn)
                sock.sendto(pkt, (SSDP_ADDR, SSDP_PORT))
            except Exception:
                pass

    def run(self):
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        if hasattr(socket, "SO_REUSEPORT"):
            try:
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
            except OSError:
                pass

        try:
            sock.bind(('', SSDP_PORT))
            # Join multicast group
            mreq = struct.pack("4sl", socket.inet_aton(SSDP_ADDR), socket.INADDR_ANY)
            sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)
            sock.settimeout(2.0)
            sys.stdout.write(f"[SSDP] Listening on UDP port {SSDP_PORT} for mobile/laptop discovery...\n")
        except Exception as e:
            sys.stderr.write(f"[SSDP Warning] Could not bind multicast port {SSDP_PORT}: {e}.\n"
                             f"[SSDP Warning] (Devices can still connect via browser or direct URL http://{self.host_ip}:{self.http_port})\n")
            return

        last_announce = 0
        while self.running:
            now = time.time()
            if now - last_announce > 60:
                self.send_announcements(sock)
                last_announce = now

            try:
                data, addr = sock.recvfrom(2048)
                msg = data.decode('utf-8', errors='ignore')
                if msg.startswith("M-SEARCH"):
                    lines = msg.split("\r\n")
                    st = None
                    for line in lines:
                        if line.upper().startswith("ST:"):
                            st = line.split(":", 1)[1].strip()
                            break

                    targets = {
                        "ssdp:all": [
                            ("upnp:rootdevice", f"{SERVER_UUID}::upnp:rootdevice"),
                            (SERVER_UUID, SERVER_UUID),
                            ("urn:schemas-upnp-org:device:MediaServer:1", f"{SERVER_UUID}::urn:schemas-upnp-org:device:MediaServer:1"),
                            ("urn:schemas-upnp-org:service:ContentDirectory:1", f"{SERVER_UUID}::urn:schemas-upnp-org:service:ContentDirectory:1"),
                        ],
                        "upnp:rootdevice": [("upnp:rootdevice", f"{SERVER_UUID}::upnp:rootdevice")],
                        SERVER_UUID: [(SERVER_UUID, SERVER_UUID)],
                        "urn:schemas-upnp-org:device:MediaServer:1": [("urn:schemas-upnp-org:device:MediaServer:1", f"{SERVER_UUID}::urn:schemas-upnp-org:device:MediaServer:1")],
                        "urn:schemas-upnp-org:service:ContentDirectory:1": [("urn:schemas-upnp-org:service:ContentDirectory:1", f"{SERVER_UUID}::urn:schemas-upnp-org:service:ContentDirectory:1")],
                    }

                    matched = targets.get(st, [])
                    for t_st, usn in matched:
                        resp = self.build_search_response(t_st, usn)
                        sock.sendto(resp, addr)
            except socket.timeout:
                continue
            except Exception:
                pass


def run_server(folder="./shared", port=DEFAULT_HTTP_PORT, host=None, name="Offline Media Server"):
    os.makedirs(folder, exist_ok=True)
    host_ip = host or get_local_ip()

    context = UPnPServerContext(host_ip, port, folder, server_name=name)
    httpd = HTTPServer(('0.0.0.0', port), UPnPRequestHandler)
    httpd.context = context

    # Start SSDP Discovery responder in background thread
    ssdp = SSDPResponder(host_ip, port, server_name=name)
    ssdp.start()

    print("=" * 65)
    print(f"🚀 {name} is running!")
    print(f"📁 Shared Folder: {os.path.abspath(folder)}")
    print(f"🌐 Offline Browser URL: http://{host_ip}:{port}")
    print(f"📡 UPnP / DLNA Discovery: Active on 239.255.255.250:{SSDP_PORT}")
    print(f"📱 Mobiles & Laptops: Connect to same Wi-Fi / Hotspot & open VLC or browser")
    print("=" * 65)
    print("Press Ctrl+C to stop.\n")

    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping server...")
        ssdp.running = False
        httpd.server_close()
        print("Done.")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Offline UPnP/DLNA & Web Media Server")
    parser.add_argument("-d", "--dir", default="./shared", help="Directory of media and files to share")
    parser.add_argument("-p", "--port", type=int, default=8000, help="HTTP Server port (default: 8000)")
    parser.add_argument("--host", default=None, help="Explicit host IP (auto-detected by default)")
    parser.add_argument("--name", default="Offline Media Server", help="Server display name for UPnP/DLNA")
    args = parser.parse_args()

    run_server(folder=args.dir, port=args.port, host=args.host, name=args.name)
