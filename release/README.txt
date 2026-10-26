MyAI - lokale Desktop-KI

Installation:
Windows: Starte MyAI-windows-x64.exe (gegebenenfalls per Doppelklick aus dem Download-Ordner).
Windows 7/8 (32-Bit): MyAI-windows-x86.exe ist ein schlanker Client fuer einen
   MyAI-Server mit lokalem Modell. Server-Adresse und Zugriffstoken stellst du unter
   "Server einstellen" ein. Anleitung: https://github.com/kobmac48-bot/MyAI/tree/main/server
Windows XP/Vista werden nicht unterstuetzt.
macOS: Oeffne die DMG-Datei und ziehe MyAI.app in den Ordner Programme.
Linux: Installiere mit
  flatpak install --user --bundle ./MyAI-linux-x64.flatpak
und starte mit
  flatpak run com.kobmac48bot.MyAI

MyAI laedt Qwen2.5-1.5B-Instruct beim ersten Start automatisch von Hugging Face
herunter. Dafuer brauchst du eine Internetverbindung und mehrere GB freien
Speicher. Mit "Modelle laden" kannst du einen fehlgeschlagenen Download erneut
starten.
Eigene Modelle kannst du in MyAI mit deinen .txt-Dateien trainieren.

Die Anwendung und das Training laufen lokal. Eigene Modelle und Trainingsdaten
bleiben auf deinem PC.
Die Lizenzbedingungen stehen in der Datei LICENSE.txt.

Optional kannst du unter "KI-Zugangsdaten" OpenAI- und Anthropic-API-Schluessel
hinterlegen und "ChatGPT + Claude" aktivieren. Dann wird dein Chatverlauf an
beide Dienste gesendet; API-Kosten koennen entstehen. Die Schluessel liegen
unverschluesselt in ai-provider-keys.json. Diese Funktion ist standardmaessig aus.
Die Gespraeche werden nicht automatisch zum Training verwendet.

Optional kannst du in MyAI einen Discord-Webhook aktivieren. Dann werden deine
Chat-Aufgabe, der Modellname und die fertige Antwort an den Discord-Kanal gesendet.
Interne Gedankengaenge werden nicht gesendet. Die Webhook-URL wird lokal gespeichert.

macOS: Diese App ist nicht von Apple signiert oder notarisiert. Beim ersten Start musst du sie
gegebenenfalls ueber Rechtsklick > Oeffnen bestaetigen.

Linux: Das Flatpak benoetigt Flatpak und laedt die Freedesktop-Laufzeit von Flathub.
