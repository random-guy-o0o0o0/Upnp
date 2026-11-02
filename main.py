import threading
from kivy.app import App
from kivy.uix.label import Label
import server

class UPnPApp(App):
    def build(self):
        server_thread = threading.Thread(target=server.run_server, daemon=True)
        server_thread.start()
        return Label(text="Offline UPnP Server is Running!\nConnect via VLC or your Browser.")

if __name__ == '__main__':
    UPnPApp().run()
