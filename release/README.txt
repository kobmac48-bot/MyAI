MyAI - lokale Desktop-KI

Installation:
Windows: Starte MyAI-windows-x64.exe (gegebenenfalls per Doppelklick aus dem Download-Ordner).
macOS: Oeffne die DMG-Datei und ziehe MyAI.app in den Ordner Programme.
Linux: Installiere mit
  flatpak install --user --bundle ./MyAI-linux-x64.flatpak
und starte mit
  flatpak run com.kobmac48bot.MyAI

Installiere Ollama von https://ollama.com und lade dort ein Chatmodell herunter,
   wenn du einen allgemeinen Chatbot verwenden moechtest.
Eigene Modelle kannst du in MyAI mit deinen .txt-Dateien trainieren.

Die Anwendung und das Training laufen lokal. Ollama wird separat installiert.
Eigene Modelle und Trainingsdaten bleiben auf deinem PC.
Die Lizenzbedingungen stehen in der Datei LICENSE.txt.

Optional kannst du in MyAI einen Discord-Webhook aktivieren. Dann werden deine
Chat-Aufgabe, der Modellname und die fertige Antwort an den Discord-Kanal gesendet.
Interne Gedankengaenge werden nicht gesendet. Die Webhook-URL wird lokal gespeichert.

macOS: Diese App ist nicht von Apple signiert oder notarisiert. Beim ersten Start musst du sie
gegebenenfalls ueber Rechtsklick > Oeffnen bestaetigen.

Linux: Das Flatpak benoetigt Flatpak und laedt die Freedesktop-Laufzeit von Flathub.
