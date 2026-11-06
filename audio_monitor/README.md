# Behringer XENYX 1204 USB Control Center

Eigenstaendige Windows-Desktop-Anwendung zur Analyse echter Audioeingangsdaten
ueber die vom Betriebssystem bereitgestellten PortAudio-Geraete. Die Anwendung
erkennt die Kanalzahl des gewaehlen Eingangs und zeigt nur diese echten
Eingangskanaele an. Die im Pult vorhandenen Mic/Line- und Stereo-Kanaele werden
als Referenz aufgefuehrt, nicht als unabhaengige USB-Eingaenge vorgetaeuscht.

## Installation

Voraussetzungen: Windows 10 oder 11, Python 3.10+ und ein vom Betriebssystem
erkanntes Audiointerface. Fuer die Entwicklung wird Python 3.11 empfohlen.

PowerShell im Repository-Verzeichnis oeffnen:

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

Anwendung starten:

```powershell
.\.venv\Scripts\python.exe start_audio_monitor.py
```

Alternativ kann `start_audio_monitor.py` mit der installierten Python-Version
gestartet werden. Es werden keine simulierten Audiodaten erzeugt. Wenn das
XENYX nicht erscheint, Windows-Audioeinstellungen und USB-Verbindung pruefen
und in der Anwendung **Aktualisieren** waehlen.

## Bedienung

1. Das Eingabegeraet mit Behringer-/USB-Namen auswaehlen. Die angezeigte
   Kanalzahl stammt direkt von der Audiogeraete-Erkennung.
2. Abtastrate und Puffer auswaehlen und **Eingang starten** druecken. Eine
   nicht unterstuetzte Kombination wird mit dem Audiofehler angezeigt; danach
   eine andere Abtastrate oder Pufferlaenge waehlen.
3. Die Kanal-Meter zeigen RMS, Peak, Signalstatus und Clipping des jeweiligen
   echten USB-Eingangskanals. Die FFT-Auswahl wechselt zwischen diesen
   Eingangskanaelen. **TRIM** beeinflusst ausschliesslich die Meterdarstellung;
   numerische dBFS-Werte und WAV-Aufnahmen bleiben unveraendert.
4. **WAV aufnehmen** speichert alle vom ausgewaehlten Geraet geoeffneten
   Kanaele als 16-bit PCM WAV. Audioaufnahme und Analyse laufen ausserhalb der
   GUI; die WAV-Datei wird von einem separaten Hintergrundthread geschrieben.

Gerate und Host-APIs werden von PortAudio gemeldet. WASAPI, DirectSound und
ASIO stehen nur zur Auswahl, wenn die jeweilige API und ein passendes
Eingabegeraet auf dem System installiert sind. Diese App greift nicht direkt
auf Mixer-Fader oder einzelne analoge Kanaele zu. Der XENYX 1204 USB stellt
keine individuellen USB-Feeds fuer alle Pultkanaele bereit. Ausgangspegel
werden nicht separat erfasst; angezeigt werden nur tatsaechlich geoeffnete
Eingangskanaele. Bufferzeit ist die rechnerische Dauer eines Audio-Blocks und
nicht die vollstaendige Round-Trip-Latenz des Treibers.

Einstellungen werden unter `%APPDATA%\Behringer XENYX 1204 USB Control
Center\settings.json` gespeichert.

## Abhaengigkeiten und Tests

Anwendungsabhaengigkeiten stehen in der Repository-`requirements.txt`.
Analyse-Unit-Tests aus dem Repository ausfuehren:

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_audio_analysis
```
