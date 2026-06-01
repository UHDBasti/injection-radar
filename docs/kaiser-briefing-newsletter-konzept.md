# Kaiser Briefing — Newsletter-Konzept

> **Status:** Konzept v1 — noch nicht aktiv
> **Owner:** Kai (KaiserIT)
> **Cadence:** Monatlich, ein Versand pro Monat (erste Woche)
> **Plattform:** Listmonk (self-hosted) auf KaiserIT-VPS (IONOS, 217.154.226.76)
> **Sprache:** Deutsch (DACH-Founder-Fokus)
> **Sekundärnutzen:** Roadmap-Drip auch für User, die keine Hosted-Plans buchen — und Trust-Aufbau für KaiserIT-Consulting (KI in Lebensmittelproduktion u. ä.)

---

## 1. Positionierung & Zielgruppe

**One-liner:** „Monatliches Briefing für deutschsprachige Founder, die KI ernst nehmen — InjectionRadar-Updates, EU-AI-Act in lesbar, ein Use Case zum Mitnehmen."

**Primäre Zielgruppe:**
- Indie-Founder / Solo-Tech-Gründer im DACH-Raum, die LLM-Agents bauen, deployen oder produktiv einsetzen.
- CTOs/Engineering-Leads kleiner SaaS-Teams (5–30 Personen), die für Compliance + Risk auf dem Stand bleiben müssen.
- Sekundär: Tech-affine Mittelständler und Berater, die KI für Kunden bewerten — Brücke zu KaiserIT-Consulting.

**Was Kaiser Briefing NICHT ist:**
- Kein Hype-Newsletter mit „Tool des Tages". Keine Affiliate-Listen.
- Keine HN-Wiederverwertung („Top 10 LLMs diesen Monat"). Nichts, das man auch via 5-min-Google findet.
- Kein Lead-Magnet-Sales-Funnel mit aggressivem CTA-Stack. Trust > Conversion-Pressure.

**Tonalität:**
- Du-Form, sachlich, leicht trocken. Wie Felix Kohlhas / Bastian Allgeier / Christoph Burgdorf schreiben — wenn jemand DE-Variante davon liefern würde.
- Konkret > abstrakt: „AI-Act Art. 6 trifft dich, wenn …" statt „regulatorische Komplexität nimmt zu".
- Bugs/Fehler offen zugeben („Letzten Monat haben wir x Domains falsch klassifiziert — hier die Korrektur").

---

## 2. Inhalts-Rubriken (Standard-Slots)

Jede Ausgabe folgt einer festen Reihenfolge, damit Abonnenten scannen können. Reihenfolge = Vertrauen + Mehrwert + Story + CTA.

| # | Rubrik | Länge | Zweck |
|---|--------|-------|-------|
| 0 | **Vorwort** — 3–5 Sätze, persönlich, ohne Marketing | ~80 Wörter | Anker, „echte Person schreibt" |
| 1 | **InjectionRadar-Updates** — neue Features, Scan-Zahlen, gefundene Domains diesen Monat | 150–250 W | Produkt-Drip, Roadmap-Transparenz |
| 2 | **EU-Regulation-Watch** — relevante AI-Act-Phasen, BSI-Hinweise, DSGVO-relevante LLM-Entscheidungen | 200–300 W | Hauptnutzen für Nicht-Kunden, primärer Share-Trigger |
| 3 | **Use Case des Monats** — wie ein DACH-Team konkret KI eingesetzt hat (Quelle: eigenes Netzwerk, Reader-Einsendung, oder eigenes Projekt) | 200–300 W | Storytelling, Inspiration, Reader-Bindung |
| 4 | **Community-Spotlight** — eine Person/ein Projekt aus dem Reader-Kreis (mit Einwilligung) | 80–120 W | Bidirektionalität, FOMO |
| 5 | **Lese-/Hör-Empfehlungen** — 3 Links max., kommentiert (kein Link-Dump) | 60 W | Kuratierung, Authentizität |
| 6 | **Outro + CTA** — was als nächstes kommt, evtl. eine konkrete Frage an die Leser | 40–60 W | Reply-Trigger (Inbox-Placement!) |

**Zielgesamtlänge:** 800–1100 Wörter. Lesedauer ~4 Min.

**Was NICHT in jede Ausgabe muss:**
- Eigener Produkt-CTA in jeder Rubrik. CTA nur Outro.
- Tool-Listen.
- Stock-Bilder. Wenn Bilder, dann eigene Screenshots oder Diagramme.

---

## 3. AI-Act-Watch — die Rubrik mit dem höchsten Reader-Nutzen

Diese Rubrik trägt das Briefing. Sie macht es zu **dem** DACH-Newsletter für Founder, die nicht 60 Min/Monat Bürokraten-PDFs lesen wollen.

**Was reinkommt:**
- Phasenpläne mit Datum + Pflicht („Ab 2. August 2026 musst du …")
- Neue Leitlinien der EU-AI-Office / nationaler Behörden (BSI, BfDI, Bundesnetzagentur)
- Konkrete Auswirkungen für SaaS/Agent-Builder (z. B. GPAI-Kategorisierung, Transparenzpflichten, Dokumentationspflichten)
- BGH-/EuGH-Urteile mit LLM-Bezug
- Ein „Was du diese Woche tun solltest"-Block (1–3 konkrete Schritte)

**Was nicht reinkommt:**
- Schon-bekannte Schlagzeilen ohne Mehrwert („Microsoft kauft …")
- Politik-Kommentare ohne praktische Konsequenz
- Spekulation („falls die EU …")

**Quelle / Recherche-Workflow:**
- Wöchentlich (Mo 30 Min) Watchlist scannen: AI-Office-Mitteilungen, BSI-Veröffentlichungen, Bitkom-PMs, ai-act-newsroom.eu, Heise Online + Golem.
- Notes in `~/diktate-content/kaiser-briefing/$(date +%Y-%m)/regulation-watch.md` sammeln.
- Zur Ausgabe: 3–5 News pro Monat auswählen, jede mit eigenem Mini-Take.

---

## 4. Editorial-Kalender (rolling)

| Zeitpunkt | Was passiert |
|-----------|--------------|
| **Monat M, ~Tag 20** | Vorwort + Use Case + Community-Spotlight schreiben (Briefing-Entwurf in Obsidian) |
| **Monat M, ~Tag 25** | InjectionRadar-Update aus Sessions/Commits extrahieren |
| **Monat M, ~Tag 28** | AI-Act-Watch finalisieren (aus monatlichen Notes) |
| **Monat M+1, ~Tag 1** | Korrektorat (1× durchlesen, laut vorlesen, Listmonk-Preview) |
| **Monat M+1, ~Tag 3 (Mi/Do, 09:00 CET)** | Versand |
| **Monat M+1, ~Tag 4** | Open-Rate / Klick-Snapshot in `kaiser-briefing/$(date +%Y-%m)/log.md` |
| **Monat M+1, ~Tag 5** | Reader-Replies beantworten (alle, persönlich) |

**Versandzeit:** Mittwoch oder Donnerstag, 9:00 CET. (Mo zu voll, Fr verbrennt, We zentriert über die Arbeitswoche.) Frühestens nach Ausgabe 3 A/B testen.

---

## 5. Tech-Setup — Listmonk auf VPS

**Stack:**
- Listmonk (latest stable, Docker-Compose)
- Postgres 16 (separater Container, Volume gemountet)
- Caddy als Reverse-Proxy (LetsEncrypt automatisch) — Caddy ist eh auf dem VPS
- Domain: `briefing.kaiserservice.consulting` (Subdomain, CNAME auf VPS-IP)
- Mail-Versand: **kein Eigen-SMTP** vom VPS. Stattdessen Transactional-Provider mit dediziertem Sub-Sender → SPF/DKIM/DMARC korrekt. Empfehlung: **Postmark Broadcast** (~9 USD/Monat bis 10k Empfänger) oder **Mailpace** (~5 EUR). Mailgun/SES gehen auch — Postmark wegen DACH-Inbox-Reputation bevorzugt.
- Backup: tägliches `pg_dump` per Cron auf den existierenden Hetzner-Storage-Box-Workflow (s. KaiserIT-VPS-Konventionen).

**Subdomain + DNS-Records (vorbereiten in einer Subtask):**
```
briefing.kaiserservice.consulting  A   217.154.226.76
kaiserservice.consulting           TXT v=spf1 include:spf.mtasv.net include:_spf.mailpace.com ~all   # je nach Provider
kaiserservice.consulting           TXT v=DMARC1; p=quarantine; rua=mailto:dmarc@kaiserservice.consulting; pct=100
mta1._domainkey.kaiserservice.consulting   CNAME   (vom Provider)
```

**Listmonk-Config-Highlights:**
- `app.address`: `0.0.0.0:9000` (Caddy upstream)
- `app.from_email`: `briefing@kaiserservice.consulting`
- `app.notify_emails`: `kai@kaiserservice.consulting`
- Admin-User mit langer Passphrase, 2FA via TOTP, Login nur über Caddy-Basic-Auth-Layer als zweiter Riegel.
- Bounce-Handling: Postmark-Webhook → Listmonk `/webhooks/bounce`.

**Datenschutz/DSGVO:**
- Double-Opt-In (Listmonk-Standard, aktiviert lassen).
- IP-Adresse bei Subscribe **nicht** speichern (Listmonk-Setting: `privacy.individual_tracking = false` oder anonymisierte Tracking-Option; Open/Klick-Tracking aggregiert ist okay, pro Subscriber lieber aus.)
- Datenschutzerklärung auf Landing erweitern: Listmonk + Postmark als Auftragsverarbeiter, AVV verlinken, Zweck, Speicherdauer, Widerruf-Link in jeder Mail (Listmonk macht das automatisch).
- Impressum + Kontakt im Footer jeder Mail (Listmonk-Template).

**Spam-Reputation-Hygiene:**
- Erste 3 Ausgaben max. 100 Empfänger pro Tag (Warm-up).
- Liste regelmäßig clean halten: Bounces auto-removed via Webhook, Soft-Bounces nach 3× hart removen.
- Reply-To = persönliche Adresse, **nicht** `noreply@`.

---

## 6. Opt-in auf der Landing — Integration

**Wo platziert:**
1. **Above-the-Fold-Hero**: nach dem H1 ein 2-Zeilen-Inline-Form (Email + Submit, keine Modal-Popups). Microcopy: „Monatliches Briefing für DACH-Founder zu KI-Sicherheit & AI-Act. Kein Spam, jederzeit kündbar."
2. **Footer**: zusätzlicher Block auf jeder Seite.
3. **Nach Scan-Ergebnis** (InjectionRadar-Frontend): kontextueller Hinweis „Diesen Scan + 1× pro Monat Briefing als Mail bekommen?" — hat höchste Conversion, weil Reader-Intent gerade hoch ist.

**Form-Backend:**
- Form POSTet an Listmonk-API (`/api/public/subscription`) — kein Eigen-Backend nötig.
- HTTP 200 → Inline-Success-State („Schau in dein Postfach für den Bestätigungslink").
- Failed → Inline-Error mit lesbarem Text.
- reCAPTCHA/hCaptcha nur falls Spam-Subscribes auftreten (erst nach Beobachtung — Friction first vermeiden).

**Tracking:**
- Conversion-Event pro Opt-In an die existierende Plausible-Instanz.
- UTM-Parameter werden in Listmonk als Subscriber-Attribute mitgespeichert (Listmonk unterstützt custom attribs) — so siehst du, welcher Kanal die besten Reader bringt.

**Microcopy-Varianten (zum A/B-Testen ab Ausgabe 3):**
- A: „Einmal im Monat: AI-Act in lesbar."
- B: „Was Founder zu KI wissen müssen — monatlich, 4 Min."
- C: „Ein Briefing pro Monat. Kein Hype, keine Tool-Listen."

---

## 7. KPIs & Erfolgskriterien

| Phase | Zeitraum | Erfolg = |
|-------|----------|----------|
| **Bootstrapping** | Ausgaben 1–3 | ≥ 50 Subscriber, Open-Rate ≥ 45 %, mindestens 3 Reader-Replies/Monat |
| **Wachstum** | Ausgaben 4–9 | ≥ 250 Subscriber, Open-Rate ≥ 40 %, ≥ 1 Lead für KaiserIT-Consulting per Reply-Konversation |
| **Etabliert** | ab Ausgabe 10 | ≥ 800 Subscriber, Open-Rate ≥ 35 %, monatlich ≥ 1 inbound Anfrage (Consulting, Pilot, Speaker-Slot, …) |

**Anti-Metriken (bewusst NICHT optimieren):**
- Click-Through-Rate auf einzelne Links → Briefing soll lesbar sein, nicht zum Wegklicken einladen
- Subscriber-Count über Lead-Magnets/Gratis-PDFs hochziehen → Reader-Qualität wichtiger
- Versandfrequenz erhöhen, um Engagement zu zeigen → monatlich ist Versprechen, monatlich bleibt es

**Kill-Kriterium:** Wenn nach Ausgabe 6 weniger als 30 Subscriber + < 25 % Open-Rate → Format ehrlich evaluieren, evtl. einstellen oder neu schneiden statt am Leben erhalten.

---

## 8. Doppelnutzen-Mechanik

Briefing dient zwei strategischen Zielen:

**a) InjectionRadar Roadmap-Drip an Free-User**
- User, die nur die Free-Tier-API nutzen, sehen über das Briefing was geplant ist — ohne dass sie unaufgefordert Sales-Mails bekommen. Wenn sie irgendwann Hosted brauchen, sind sie bereits warm.
- Rubrik 1 ist der natürliche Ort dafür.

**b) KaiserIT-Consulting Lead-Generation (langfristig, Schwartauer-Spur)**
- Reader, die im Use-Case-Block oder Reply-Verkehr auftauchen, sind potenziell „KI-in-Lebensmittelproduktion"/Mittelstand-Profile.
- Briefing positioniert Kai als jemand, der **technisch tief drin** ist (durch InjectionRadar) UND **regulatorisch tief drin** (durch AI-Act-Watch). Genau der Trust, den Mittelstands-Entscheider für Consulting-Engagements brauchen.
- KaiserIT-Consulting wird im Briefing **nicht** beworben. Trust entsteht durch Inhalte, Geschäft entsteht durch Replies und Folgegespräche.

---

## 9. Risiken & Pitfalls

1. **AI-Act-Watch driftet in Politik-Kommentar.** → strenge Reader-Frage: „Was muss ich diese Woche tun?" Wenn Antwort fehlt, Punkt streichen.
2. **Monatlicher Schreibaufwand wird zu groß.** → Editorial-Kalender ernst nehmen, Rubrik 3 (Use Case) kann auch ein eigenes vergangenes Projekt sein wenn keine externe Story verfügbar; Rubrik 5 (Empfehlungen) zur Not auf 2 Links kürzen.
3. **Listmonk-Versand wirft IP/Domain in Spam.** → daher Postmark als Transactional-Schicht, kein Eigen-SMTP. Erste 3 Ausgaben Warm-up. SPF/DKIM/DMARC vor Ausgabe 1 verifiziert (z. B. via `mail-tester.com` Score ≥ 9/10).
4. **Community-Spotlight ohne Einwilligung.** → immer schriftlich nachfragen, auch wenn das Zitat öffentlich war (vgl. Diktate-Content-Skill, gleiche Regel).
5. **Briefing kannibalisiert injectionradar-Newsletter (falls separat geplant).** → einer pro Channel. Kaiser Briefing = Kai-Branding, KaiserIT-Audience. Falls InjectionRadar-Produkt einen eigenen Update-Drip braucht, separat denken (z. B. In-App + Statuspage-RSS).

---

## 10. Out-of-Scope für diese Task

Diese Task liefert **nur das Konzept**. Implementierung wird in Subtasks abgespalten:

- **`feat/listmonk-deploy`** — Listmonk-Container auf VPS, Caddy-Routing, Postgres, Postmark-Anbindung, SPF/DKIM/DMARC einrichten
- **`feat/landing-newsletter-opt-in`** — InjectionRadar-Landing um Hero-Form + Footer-Form + Post-Scan-CTA erweitern, POST an Listmonk-API
- **`content/kaiser-briefing-issue-01`** — Erste Ausgabe schreiben (sobald Listmonk live ist)
- **`docs/datenschutz-briefing-erweiterung`** — Datenschutzerklärung + AVV-Listen aktualisieren
- **`ops/briefing-warmup-plan`** — Warm-up-Liste der ersten 100 manuell hand-rekrutierten Subscriber (persönliches Netzwerk, frühe InjectionRadar-User, Bekannte aus DACH-Tech-Bubble) — wichtig für Inbox-Reputation und ehrliches Feedback

---

## Quellen & Referenzen

- Listmonk-Doku: <https://listmonk.app/docs/>
- Postmark-Broadcast: <https://postmarkapp.com/broadcast-email>
- AI-Act offizielle Phasen: <https://artificialintelligenceact.eu/implementation-timeline/>
- BSI-LLM-Leitfäden: <https://www.bsi.bund.de/> (LLM-Schlagworte)
- Vergleichsbenchmarks für DACH-Newsletter-Stimme: Felix Kohlhas „Was mir auffiel", Ole Reißmann „Update". Nicht nachahmen, aber als Qualitätslatte denken.

---

*Konzept v1 — Reviews willkommen. Änderungen am Konzept gehören in PRs gegen diese Datei, nicht in einzelne Issue-Kommentare.*
