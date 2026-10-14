import base64
import os
import threading
import urllib.parse
from collections import defaultdict

import anthropic
import requests
from flask import Flask, request
from twilio.rest import Client as Twilio

# ---------- PODEŠAVANJE ----------
# Potrebne env promenljive:
#   ANTHROPIC_API_KEY, TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN
#   TWILIO_WHATSAPP_NUMBER (opciono, default je Twilio sandbox broj)
MODEL = "claude-sonnet-5-5"
BOT_IME = "Domaćko"

SID = os.environ["TWILIO_ACCOUNT_SID"]
TOKEN = os.environ["TWILIO_AUTH_TOKEN"]
FROM = os.environ.get("TWILIO_WHATSAPP_NUMBER", "whatsapp:+14155238886")

app = Flask(__name__)
ai = anthropic.Anthropic()
twilio = Twilio(SID, TOKEN)
ISTORIJA = defaultdict(list)  # kratka istorija razgovora po korisniku

SISTEM = (
    f"Ti si {BOT_IME}, WhatsApp bot koji govori srpski (latinica, osim ako korisnik "
    "piše drugačije). Pametan si i prijateljski, odgovaraš jasno i kratko jer je ovo "
    "WhatsApp. Ti si bot po imenu " + BOT_IME + ". Nisi ChatGPT i nisi OpenAI proizvod. "
    "Ako te pitaju ko si, reci da si " + BOT_IME + ", bot za WhatsApp. Ako te pitaju koji "
    "se model nalazi iza tebe, reci da to ne možeš da otkriješ. "
    "Ne koristi markdown tabele ni naslove; WhatsApp podržava samo *bold* i _italic_."
)

SISTEM_DOMACI = SISTEM + (
    " Sada radiš domaći zadatak. Reši zadatak korak po korak, objasni postupak "
    "kratko i na kraju jasno napiši konačan odgovor."
)

POMOC = (
    f"Ja sam *{BOT_IME}*, bot za WhatsApp 🤖\n\n"
    "*!uradi* <zadatak> - uradim domaći (možeš da pošalješ i sliku zadatka)\n"
    "*!napravi* <opis> - napravim sliku\n"
    "*!pitaj* <pitanje> - pričaj sa mnom o bilo čemu\n"
    "*!reset* - zaboravim razgovor\n"
    "*!pomoc* - ova poruka"
)


# ---------- POMOĆNE FUNKCIJE ----------
def posalji(to, tekst=None, slika=None):
    if tekst:
        for i in range(0, len(tekst), 1500):
            twilio.messages.create(from_=FROM, to=to, body=tekst[i:i + 1500])
    if slika:
        twilio.messages.create(from_=FROM, to=to, media_url=[slika], body="Evo slike 🎨")


def pitaj_ai(sistem, poruke):
    r = ai.messages.create(model=MODEL, max_tokens=1500, system=sistem, messages=poruke)
    return "".join(b.text for b in r.content if b.type == "text").strip()


def skini_sliku(url):
    r = requests.get(url, auth=(SID, TOKEN), timeout=30)
    r.raise_for_status()
    tip = r.headers.get("Content-Type", "image/jpeg").split(";")[0]
    return tip, base64.standard_b64encode(r.content).decode()


# ---------- KOMANDE ----------
def obradi(sender, body, media_url, media_tip):
    try:
        cmd, _, arg = body.partition(" ")
        cmd, arg = cmd.lower(), arg.strip()

        if cmd == "!pomoc":
            posalji(sender, POMOC)

        elif cmd == "!reset":
            ISTORIJA.pop(sender, None)
            posalji(sender, "Zaboravio sam sve o čemu smo pričali ✅")

        elif cmd == "!napravi":
            if not arg:
                posalji(sender, "Napiši šta da napravim, npr: *!napravi mačka u svemirskom odelu*")
                return
            posalji(sender, "Crtam, sačekaj malo... 🎨")
            url = ("https://image.pollinations.ai/prompt/" + urllib.parse.quote(arg)
                   + "?width=1024&height=1024&nologo=true")
            posalji(sender, slika=url)

        elif cmd == "!uradi":
            sadrzaj = []
            if media_url and media_tip.startswith("image/"):
                tip, data = skini_sliku(media_url)
                sadrzaj.append({"type": "image",
                                "source": {"type": "base64", "media_type": tip, "data": data}})
            if not arg and not sadrzaj:
                posalji(sender, "Napiši zadatak ili pošalji sliku sa *!uradi* u opisu.")
                return
            sadrzaj.append({"type": "text", "text": arg or "Reši zadatak sa slike."})
            posalji(sender, "Radim na tome... ✏️")
            odgovor = pitaj_ai(SISTEM_DOMACI, [{"role": "user", "content": sadrzaj}])
            posalji(sender, odgovor)

        elif cmd == "!pitaj":
            if not arg:
                posalji(sender, "Šta želiš da pitaš? Npr: *!pitaj zašto je nebo plavo*")
                return
            ISTORIJA[sender].append({"role": "user", "content": arg})
            odgovor = pitaj_ai(SISTEM, ISTORIJA[sender])
            ISTORIJA[sender].append({"role": "assistant", "content": odgovor})
            ISTORIJA[sender] = ISTORIJA[sender][-20:]
            posalji(sender, odgovor)

        else:
            posalji(sender, "Ne znam tu komandu 🤔 Piši *!pomoc*")

    except Exception as e:
        print("GREŠKA:", e)
        posalji(sender, "Ups, nešto je pošlo naopako 😅 Probaj opet.")


@app.post("/whatsapp")
def whatsapp():
    sender = request.form.get("From", "")
    body = (request.form.get("Body") or "").strip()
    media_url = request.form.get("MediaUrl0")
    media_tip = request.form.get("MediaContentType0", "")

    if not body.startswith("!"):
        posalji(sender, f"Zdravo, ja sam {BOT_IME} 👋 Komande počinju sa !, piši *!pomoc*")
    else:
        # odgovor šaljemo u pozadini da Twilio ne istekne (limit ~15s)
        threading.Thread(target=obradi, args=(sender, body, media_url, media_tip),
                         daemon=True).start()
    return ("", 204)


if __name__ == "__main__":
    app.run(port=5000)
