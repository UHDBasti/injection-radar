"""
Red-Flag Detector für InjectionRadar.

Analysiert LLM-Outputs UND Website-Content auf Anzeichen von Prompt Injection.
"""

import base64
import html as html_module
import re
import unicodedata
from typing import Optional
from urllib.parse import unquote

from ..core.models import RedFlag, RedFlagType, Severity


class RedFlagDetector:
    """Erkennt Red Flags in LLM-Outputs und Website-Content."""

    # =========================================================================
    # LLM-Output Patterns (bestehend)
    # =========================================================================

    TOOL_CALL_PATTERNS = [
        r"<tool_call>",
        r"<function_call>",
        r"\{\s*\"name\":\s*\"",
        r"```tool_code",
        r"I'll call the .+ function",
        r"Let me execute",
        r"I'll use the .+ tool",
    ]

    CODE_EXECUTION_PATTERNS = [
        r"```python\s*\n.*?(exec|eval|subprocess|os\.system)",
        r"import os\s*\n.*?os\.(system|popen|exec)",
        r"```bash\s*\n.*?(rm |curl |wget )",
        r"```sh\s*\n",
        r"<script>.*?</script>",
        r"javascript:",
    ]

    SYSTEM_PROMPT_PATTERNS = [
        r"system prompt",
        r"initial instructions",
        r"my instructions are",
        r"I was told to",
        r"my guidelines say",
        r"according to my system",
        r"as an AI assistant, I",
    ]

    INSTRUCTION_PATTERNS = [
        r"ignore\s+(all\s+)?(the\s+)?(previous\s+|above\s+)?instructions",
        r"disregard\s+(all\s+)?(the\s+)?(previous\s+|above\s+)?instructions",
        r"forget\s+(all\s+)?(the\s+)?(previous\s+|above\s+)?instructions",
        r"new instructions:",
        r"you must now",
        r"your new task is",
        r"instead,?\s*(you should|please|do)",
        r"IMPORTANT:.*follow",
        r"SYSTEM:.*override",
    ]

    EXTERNAL_URL_PATTERNS = [
        r"https?://(?!(?:www\.)?(?:google|bing|yahoo|wikipedia)\.)[^\s<>\"]+",
        r"click here",
        r"visit this link",
        r"download from",
    ]

    # =========================================================================
    # Content Injection Patterns (NEU)
    # =========================================================================

    # a) Direkte Injection-Anweisungen im Website-Content
    CONTENT_INJECTION_PATTERNS = [
        # --- English ---
        r"ignore\s+(all\s+)?(the\s+)?(previous\s+|prior\s+|above\s+)?instructions",
        r"disregard\s+(all\s+)?(the\s+)?(previous\s+|prior\s+|above\s+)?instructions",
        r"forget\s+(all\s+)?(the\s+)?(previous\s+|prior\s+|above\s+)?(instructions|context|everything)",
        r"do\s+not\s+follow\s+(the\s+)?(previous\s+|prior\s+|above\s+|original\s+)?instructions",
        r"override\s+(all\s+)?(the\s+)?(previous\s+|prior\s+)?instructions",
        r"you\s+are\s+now\s+(a|an|the)\b",
        r"your\s+new\s+(role|task|instructions?|objective|purpose)\s+(is|are)",
        r"new\s+instructions?\s*:",
        r"from\s+now\s+on,?\s+you\s+(are|will|must|should)",
        r"instead\s+of\s+summariz(e|ing)",
        r"do\s+not\s+summarize",
        r"stop\s+being\s+(a|an)\s+",
        r"you\s+must\s+(now|instead|always)\s+",
        r"the\s+assistant\s+is\s+in\s+error",
        r"assistant\s+is\s+(?:now\s+)?offline",
        r"an?\s+(?:unrestricted|unfiltered)\s+(?:AI|bot|assistant|model)",
        r"does?\s+the\s+jobs?\s+as\s+the\s+assistant",
        r"(?:find|get|obtain|extract)\s+(?:out\s+)?(?:the\s+)?user'?s?\s+(?:real\s+)?(?:name|email|password|data|information)",
        # --- Deutsch ---
        r"ignorier(?:e|en?)\s+(alle\s+)?(?:vorherigen?\s+|bisherigen?\s+|obigen?\s+)?(?:Anweisungen|Instruktionen|Befehle)",
        r"vergiss\s+(alle\s+)?(?:vorherigen?\s+|bisherigen?\s+)?(?:Anweisungen|Instruktionen|Befehle|alles)",
        r"(?:befolge|beachte)\s+(die\s+)?(?:vorherigen?\s+|bisherigen?\s+)?(?:Anweisungen|Instruktionen)\s+nicht",
        r"(?:überschreib|ersetze)\s+(alle\s+)?(?:vorherigen?\s+)?(?:Anweisungen|Instruktionen)",
        r"du\s+bist\s+(?:jetzt|nun|ab\s+sofort)\s+(ein|eine|der|die)\b",
        r"deine\s+neue\s+(Rolle|Aufgabe|Anweisung|Instruktion)\s+(ist|lautet)",
        r"neue\s+(?:Anweisungen?|Instruktionen?)\s*:",
        r"ab\s+(?:jetzt|sofort)\s+(?:bist|sollst|musst|wirst)\s+du",
        r"fasse?\s+(?:nicht\s+)?zusammen",
        r"du\s+(?:musst|sollst)\s+(?:jetzt|nun|stattdessen|ab\s+sofort)",
        r"(?:ein|eine)\s+(?:uneingeschränkte[rs]?|unzensierte[rs]?)\s+(?:KI|Bot|Assistent|Modell)",
        # --- Français ---
        r"ignor(?:e|ez|er)\s+(toutes?\s+)?(?:les?\s+)?(?:instructions?\s+|consignes?\s+)?(?:précédentes?|antérieures?|ci-dessus)",
        r"oubli(?:e|ez|er)\s+(toutes?\s+)?(?:les?\s+)?(?:instructions?\s+)?(?:précédentes?|antérieures?)",
        r"(?:ne\s+)?sui(?:s|vez)\s+(?:pas\s+)?(?:les?\s+)?instructions?\s+précédentes?",
        r"tu\s+es\s+(?:maintenant|désormais)\s+(un|une|le|la)\b",
        r"(?:ta|votre)\s+nouvelle\s+(?:mission|rôle|tâche|instruction)\s+(?:est|consiste)",
        r"nouvelles?\s+instructions?\s*:",
        r"à\s+partir\s+de\s+maintenant",
        # --- Español ---
        r"ignora\s+(todas?\s+)?(?:las?\s+)?(?:instrucciones?\s+)?(?:anteriores?|previas?)",
        r"olvida\s+(todas?\s+)?(?:las?\s+)?(?:instrucciones?\s+)?(?:anteriores?|previas?|todo)",
        r"no\s+(?:sigas?|cumplas?)\s+(?:las?\s+)?instrucciones?\s+(?:anteriores?|previas?)",
        r"(?:ahora\s+)?eres\s+(?:un|una|el|la)\b",
        r"tu\s+nuev[oa]\s+(?:rol|tarea|instrucción|objetivo)\s+(?:es|será)",
        r"nuevas?\s+instrucciones?\s*:",
        r"a\s+partir\s+de\s+ahora",
        # --- Português ---
        r"ignor(?:e|ar)\s+(todas?\s+)?(?:as?\s+)?(?:instruções?\s+)?(?:anteriores?|prévias?)",
        r"esqueç(?:a|er)\s+(todas?\s+)?(?:as?\s+)?(?:instruções?\s+)?(?:anteriores?|prévias?|tudo)",
        r"(?:agora\s+)?você\s+é\s+(?:um|uma|o|a)\b",
        r"(?:sua|tua)\s+nov[oa]\s+(?:função|tarefa|instrução)\s+(?:é|será)",
        # --- Italiano ---
        r"ignora\s+(tutte?\s+)?(?:le?\s+)?(?:istruzioni?\s+)?(?:precedenti?|anteriori?)",
        r"dimentica\s+(tutte?\s+)?(?:le?\s+)?(?:istruzioni?\s+)?(?:precedenti?|anteriori?|tutto)",
        r"(?:ora\s+)?(?:sei|sarai)\s+(?:un|una|il|la)\b.*?(?:assistente|modello|bot)",
        r"nuov[ae]\s+istruzioni?\s*:",
        # --- Russisch (transliteriert + kyrillisch) ---
        r"игнорируй\s+(?:все\s+)?(?:предыдущие\s+)?(?:инструкции|указания|команды)",
        r"забудь\s+(?:все\s+)?(?:предыдущие\s+)?(?:инструкции|указания|команды|всё)",
        r"ты\s+(?:теперь|сейчас)\s+",
        r"новые\s+(?:инструкции|указания|команды)\s*:",
        # --- Chinesisch ---
        r"忽略\s*(?:所有\s*)?(?:之前|先前|以上)\s*(?:的\s*)?(?:指令|指示|说明)",
        r"忘记\s*(?:所有\s*)?(?:之前|先前)\s*(?:的\s*)?(?:指令|指示|说明|一切)",
        r"你现在是",
        r"新的?(?:指令|指示|说明|角色|任务)\s*[：:]",
        # --- Japanisch ---
        r"(?:以前|前|これまで)の(?:指示|命令|指令)を(?:無視|忘れ|忘却)",
        r"(?:今から|これから)(?:あなた|お前)は",
        r"新しい(?:指示|命令|指令|役割)\s*[：:]",
        # --- Koreanisch ---
        r"(?:이전|이전의|위의)\s*(?:지시|명령|지침)을?\s*(?:무시|잊어)",
        r"(?:지금부터|이제부터)\s*(?:너는|당신은)",
        r"새로운\s*(?:지시|명령|지침|역할)\s*[：:]",
        # --- Arabisch ---
        r"تجاهل\s+(?:جميع\s+)?(?:التعليمات|الأوامر|الإرشادات)\s+(?:السابقة|أعلاه)",
        r"أنت\s+الآن\s+",
        r"تعليمات\s+جديدة\s*[：:]",
    ]

    # b) Fake System/Role Tags
    FAKE_SYSTEM_TAG_PATTERNS = [
        r"\[system\]",
        r"\[INST\]",
        r"\[/INST\]",
        r"<\|system\|>",
        r"<\|im_start\|>",
        r"<\|im_end\|>",
        r"<\|user\|>",
        r"<\|assistant\|>",
        r"###\s*(System|Assistant|Human|User)\s*:",
        r"<s>.*?</s>",
        r"<<SYS>>",
        r"<</SYS>>",
        r"\[SYSTEM\]",
        r"SYSTEM\s*PROMPT\s*:",
        r"BEGIN\s*SYSTEM\s*MESSAGE",
        # Bing Chat specific markers
        r"\[system\]\(#[a-z_]+\)",
        r"\[assistant\]\(#[a-z_]+\)",
        r"\[user\]\(#[a-z_]+\)",
        r"#error_state",
        r"#inner_monologue",
        r"#search_results",
    ]

    # c) Exfiltration Patterns im Content
    EXFILTRATION_PATTERNS = [
        r"!\[.*?\]\(https?://[^\s)]*(?:steal|exfil|leak|log|collect|track)[^\s)]*\)",
        r"!\[.*?\]\(https?://[^\s)]*\?(?:data|q|query|input|text|content)=",
        r"!\[\]\(https?://[^\s)]+\)",  # Empty alt-text markdown image (suspicious)
        r"fetch\s*\(",
        r"XMLHttpRequest",
        r"navigator\.sendBeacon",
        r"new\s+Image\(\)\.src\s*=",
        r"document\.location\s*=",
        r"window\.location\s*=.*\+",
        # Tunneling services used for data exfiltration
        r"https?://[^\s]*\.ngrok\.io\b",
        r"https?://[^\s]*\.trycloudflare\.com\b",
        r"https?://[^\s]*\.serveo\.net\b",
    ]

    # d) Jailbreak Patterns
    JAILBREAK_PATTERNS = [
        # --- English ---
        r"\bDAN\b(?:\s+mode)?",
        r"Do\s+Anything\s+Now",
        r"Now[- ]?Do[- ]?Anything",
        r"\bjailbreak(?:ed|ing)?\b",
        r"pretend\s+you\s+are\b",
        r"act\s+as\s+if\s+you\b",
        r"roleplay\s+as\b",
        r"no\s+restrictions",
        r"no\s+limitations",
        r"\bunrestricted\b",
        r"developer\s+mode",
        r"maintenance\s+mode",
        r"god\s+mode",
        r"sudo\s+mode",
        r"emergency\s+mode",
        r"without\s+(any\s+)?(?:limits|constraints|restrictions|limitations)",
        r"without\s+(any\s+)?(?:ethical|safety|content)\s+(?:guidelines|filters|restrictions)",
        r"bypass\s+(?:your\s+)?(?:safety|content|ethical)\s+(?:filters?|guidelines?|restrictions?)",
        r"not\s+restricted\s+by\s+(the\s+)?rules",
        r"is\s+in\s+error\s+and\s+offline",
        r"secret\s+agend[as]?",
        # --- Deutsch ---
        r"keine\s+(?:Einschränkungen|Beschränkungen|Grenzen|Limitierungen)",
        r"\buneingeschränkt\b",
        r"Entwicklermodus",
        r"Wartungsmodus",
        r"Gott[- ]?Modus",
        r"ohne\s+(?:jegliche\s+)?(?:Einschränkungen|Beschränkungen|Grenzen|Limits|Regeln)",
        r"ohne\s+(?:ethische\s+|sicherheits\s*)?(?:Richtlinien|Filter|Vorgaben)",
        r"(?:umgehe?|umgehen|überspring)\s+(?:die\s+)?(?:Sicherheits|Inhalts)[- ]?(?:filter|richtlinien|regeln)",
        r"nicht\s+(?:durch\s+)?(?:die\s+)?Regeln\s+(?:eingeschränkt|beschränkt|begrenzt)",
        r"tu(?:e|st)?\s+(?:jetzt\s+)?alles\s+was\s+ich\s+(?:sage|will|verlange)",
        r"geheime[rs]?\s+(?:Agenda|Auftrag|Mission|Ziel)",
        r"(?:gib|tu)\s+(?:so\s+)?(?:als\s+ob|vor)\s+du\s+(?:wärst|bist)",
        # --- Français ---
        r"(?:aucune|sans)\s+(?:restriction|limitation|contrainte)s?",
        r"\bsans\s+(?:filtre|limite)s?\b",
        r"mode\s+(?:développeur|maintenance|dieu|urgence)",
        r"(?:fais|faites)\s+(?:semblant|comme\s+si)\s+(?:tu\s+es|vous\s+êtes)",
        r"(?:contourne|ignore)[rz]?\s+(?:les?\s+)?(?:filtres?|restrictions?|règles?)\s+(?:de\s+)?(?:sécurité|contenu|éthique)",
        r"agenda\s+secr[eè]te?",
        # --- Español ---
        r"(?:sin|ninguna)\s+(?:restriccion|limitación|restricciones|limitaciones)",
        r"modo\s+(?:desarrollador|mantenimiento|dios|emergencia)",
        r"(?:finge|simula|actúa\s+como\s+si)\s+(?:eres|fueras)\b",
        r"(?:evita|elude|salta)\s+(?:los?\s+)?(?:filtros?|restricciones?|reglas?)\s+(?:de\s+)?(?:seguridad|contenido)",
        r"agenda\s+secreta",
        # --- Russisch ---
        r"(?:без|никаких)\s+(?:ограничений|лимитов|рамок)",
        r"режим\s+(?:разработчика|бога|обслуживания)",
        r"(?:притворись|представь)\s+(?:что\s+)?(?:ты|вы)",
        r"(?:обойди|игнорируй)\s+(?:все\s+)?(?:фильтры|ограничения|правила)",
        # --- Chinesisch ---
        r"(?:没有|无|不受)\s*(?:限制|约束|规则)",
        r"(?:开发者|维护|上帝|紧急)\s*模式",
        r"(?:假装|扮演|充当)\s*(?:你是|你现在是)",
        r"(?:绕过|忽略|跳过)\s*(?:安全|内容)?\s*(?:过滤|限制|规则)",
        # --- Japanisch ---
        r"(?:制限|制約)\s*(?:なし|なく|のない)",
        r"(?:開発者|メンテナンス|ゴッド)\s*モード",
        r"(?:のふりをして|になりきって|を演じて)",
        # --- Koreanisch ---
        r"(?:제한|제약)\s*(?:없이|없는|없음)",
        r"(?:개발자|유지보수|신)\s*모드",
        r"(?:인척|처럼)\s*(?:행동|연기)",
    ]

    # e) Hidden text CSS patterns (für raw HTML)
    HIDDEN_TEXT_CSS_PATTERNS = [
        r"font-size\s*:\s*0(?:px|em|rem|pt|%)?\s*[;\"]",
        r"display\s*:\s*none",
        r"visibility\s*:\s*hidden",
        r"opacity\s*:\s*0\s*[;\"]",
        r"color\s*:\s*(?:white|#fff(?:fff)?|rgba?\s*\(\s*255\s*,\s*255\s*,\s*255)\s*[;\"].*?background(?:-color)?\s*:\s*(?:white|#fff(?:fff)?|rgba?\s*\(\s*255\s*,\s*255\s*,\s*255)",
        r"position\s*:\s*(?:absolute|fixed)\s*;[^}]*?(?:left|top)\s*:\s*-\d{4,}px",
        r"text-indent\s*:\s*-\d{4,}px",
        r"overflow\s*:\s*hidden\s*;[^}]*?(?:height|width)\s*:\s*0",
        r"clip\s*:\s*rect\s*\(\s*0",
    ]

    @staticmethod
    def _normalize_text(text: str) -> str:
        """Normalize text to prevent Unicode bypass attacks."""
        # NFKC normalization (converts fullwidth, compatibility chars to standard forms)
        text = unicodedata.normalize("NFKC", text)
        # Remove zero-width characters
        text = re.sub(r'[\u200b\u200c\u200d\u200e\u200f\ufeff\u2060\u2061\u2062\u2063\u2064]', '', text)
        # Remove other invisible formatting characters
        text = re.sub(r'[\u00ad\u034f\u115f\u1160\u17b4\u17b5\u180e]', '', text)
        # Remove RTL/LTR override characters
        text = re.sub(r'[\u202a\u202b\u202c\u202d\u202e\u2066\u2067\u2068\u2069]', '', text)
        return text

    @staticmethod
    def _decode_text(text: str) -> str:
        """Decode URL-encoded and HTML entity sequences."""
        decoded = unquote(text)
        decoded = html_module.unescape(decoded)
        return decoded

    @staticmethod
    def _detect_rtl_overrides(original_text: str) -> Optional[RedFlag]:
        """Detect RTL/LTR override characters before normalization strips them."""
        rtl_chars = re.findall(r'[\u202a-\u202e\u2066-\u2069]', original_text)
        if rtl_chars:
            return RedFlag(
                type=RedFlagType.FORMAT_DEVIATION,
                severity=Severity.HIGH,
                description=f"RTL/LTR override characters detected ({len(rtl_chars)} found) - possible text direction attack",
                evidence=f"Found {len(rtl_chars)} directional override characters",
            )
        return None

    def detect_content_injection(
        self,
        extracted_text: str,
        raw_html: Optional[str] = None,
    ) -> list[RedFlag]:
        """Erkennt Injection-Patterns im Website-Content selbst.

        Analysiert den extrahierten Text UND optional das Raw-HTML
        auf Anzeichen, dass die Seite Prompt Injection enthält.

        Args:
            extracted_text: Der extrahierte Klartext der Website.
            raw_html: Das rohe HTML (für Hidden-Text-Detection).

        Returns:
            Liste der erkannten RedFlags.
        """
        flags = []

        # RTL override detection BEFORE normalization (normalization strips them)
        rtl_flag = self._detect_rtl_overrides(extracted_text)
        if rtl_flag:
            flags.append(rtl_flag)

        # Unicode normalization before pattern matching
        text_normalized = self._normalize_text(extracted_text)

        # Additionally decode URL-encoding and HTML entities
        text_decoded = self._decode_text(text_normalized)

        # Collect texts to run pattern matching against
        texts_to_check = [text_normalized]
        if text_decoded != text_normalized:
            texts_to_check.append(text_decoded)

        # a) Direkte Injection-Anweisungen (HIGH)
        for text_variant in texts_to_check:
            injection_flags = self._detect_patterns(
                text_variant,
                self.CONTENT_INJECTION_PATTERNS,
                RedFlagType.CONTENT_INJECTION,
                Severity.HIGH,
                "Injection instructions found in website content",
            )
            if injection_flags:
                flags.extend(injection_flags)
                break

        # b) Fake System/Role Tags (HIGH)
        for text_variant in texts_to_check:
            system_tag_flags = self._detect_patterns(
                text_variant,
                self.FAKE_SYSTEM_TAG_PATTERNS,
                RedFlagType.CONTENT_INJECTION,
                Severity.HIGH,
                "Fake system/role tags found in website content",
            )
            if system_tag_flags:
                flags.extend(system_tag_flags)
                break

        # c) Exfiltration Patterns (CRITICAL)
        for text_variant in texts_to_check:
            exfil_flags = self._detect_patterns(
                text_variant,
                self.EXFILTRATION_PATTERNS,
                RedFlagType.CONTENT_INJECTION,
                Severity.CRITICAL,
                "Data exfiltration pattern found in website content",
            )
            if exfil_flags:
                flags.extend(exfil_flags)
                break

        # d) Jailbreak Patterns (HIGH)
        for text_variant in texts_to_check:
            jailbreak_flags = self._detect_patterns(
                text_variant,
                self.JAILBREAK_PATTERNS,
                RedFlagType.CONTENT_INJECTION,
                Severity.HIGH,
                "Jailbreak pattern found in website content",
            )
            if jailbreak_flags:
                flags.extend(jailbreak_flags)
                break

        # e) Hidden Text Detection (CRITICAL) - benötigt raw HTML
        if raw_html:
            hidden_flags = self._detect_hidden_text(raw_html)
            flags.extend(hidden_flags)

        # f) Obfuscation Detection (use original text for zero-width detection)
        obfuscation_flags = self._detect_obfuscation(extracted_text)
        flags.extend(obfuscation_flags)

        return flags

    def _detect_hidden_text(self, raw_html: str) -> list[RedFlag]:
        """Erkennt versteckten Text im HTML, der Injection-Patterns enthält.

        Sucht nach CSS-Techniken die Text unsichtbar machen und prüft
        ob der versteckte Text Injection-Muster enthält.
        """
        flags = []
        html_lower = raw_html.lower()

        # Suche nach Elementen mit versteckendem CSS die Text enthalten
        # Pattern: style="...hiding-css..." mit Text-Inhalt
        hidden_element_patterns = [
            # font-size:0 with content
            r'<[^>]+style\s*=\s*"[^"]*font-size\s*:\s*0(?:px|em|rem|pt)?\s*[^"]*"[^>]*>([^<]+)',
            # display:none with content
            r'<[^>]+style\s*=\s*"[^"]*display\s*:\s*none[^"]*"[^>]*>([^<]+)',
            # visibility:hidden with content
            r'<[^>]+style\s*=\s*"[^"]*visibility\s*:\s*hidden[^"]*"[^>]*>([^<]+)',
            # opacity:0 with content
            r'<[^>]+style\s*=\s*"[^"]*opacity\s*:\s*0\s*[^"]*"[^>]*>([^<]+)',
            # position off-screen with content
            r'<[^>]+style\s*=\s*"[^"]*position\s*:\s*(?:absolute|fixed)[^"]*(?:left|top)\s*:\s*-\d{4,}px[^"]*"[^>]*>([^<]+)',
            # color same as background (white on white)
            r'<[^>]+style\s*=\s*"[^"]*color\s*:\s*(?:white|#fff(?:fff)?|rgb\s*\(\s*255)[^"]*"[^>]*>([^<]+)',
        ]

        for pattern in hidden_element_patterns:
            matches = re.findall(pattern, html_lower, re.DOTALL | re.IGNORECASE)
            for match in matches:
                hidden_text = match.strip()
                if len(hidden_text) < 5:
                    continue

                # Prüfe ob der versteckte Text Injection-Muster enthält
                has_injection = self._text_contains_injection(hidden_text)
                if has_injection:
                    flags.append(RedFlag(
                        type=RedFlagType.CONTENT_INJECTION,
                        severity=Severity.CRITICAL,
                        description="Hidden text with injection patterns detected (CSS hiding)",
                        evidence=hidden_text[:200],
                    ))
                    return flags  # Ein Fund reicht

        # Auch nach CSS-Klassen suchen die Text verstecken
        # z.B. <style>.hidden { font-size: 0 }</style> ... <span class="hidden">inject</span>
        for pattern in self.HIDDEN_TEXT_CSS_PATTERNS:
            if re.search(pattern, html_lower, re.IGNORECASE):
                # Es gibt versteckendes CSS - prüfe ob es verdächtig mit Injection korreliert
                # Einfache Heuristik: Wenn die Seite sowohl hiding-CSS als auch
                # Injection-Keywords im selben HTML hat
                if self._text_contains_injection(html_lower):
                    flags.append(RedFlag(
                        type=RedFlagType.CONTENT_INJECTION,
                        severity=Severity.HIGH,
                        description="Page uses CSS text-hiding techniques alongside injection patterns",
                        evidence=f"CSS pattern: {pattern[:80]}",
                    ))
                    return flags  # Ein Fund reicht

        return flags

    def _text_contains_injection(self, text: str) -> bool:
        """Prüft ob ein Text Injection-Patterns enthält."""
        text_lower = text.lower()
        all_patterns = (
            self.CONTENT_INJECTION_PATTERNS
            + self.FAKE_SYSTEM_TAG_PATTERNS
            + self.JAILBREAK_PATTERNS
        )
        for pattern in all_patterns:
            if re.search(pattern, text_lower, re.IGNORECASE):
                return True
        return False

    def _detect_obfuscation(self, text: str) -> list[RedFlag]:
        """Erkennt obfuskierte Injection-Versuche.

        Prüft auf Base64-encoded Injections und Unicode-Tricks.
        """
        flags = []

        # Base64-Blöcke finden und auf Injection-Keywords prüfen
        b64_pattern = r"[A-Za-z0-9+/]{20,}={0,2}"
        b64_matches = re.findall(b64_pattern, text)
        for b64_match in b64_matches[:10]:  # Max 10 prüfen
            try:
                decoded = base64.b64decode(b64_match).decode("utf-8", errors="ignore")
                if self._text_contains_injection(decoded):
                    flags.append(RedFlag(
                        type=RedFlagType.CONTENT_INJECTION,
                        severity=Severity.HIGH,
                        description="Base64-encoded injection pattern found",
                        evidence=f"Decoded: {decoded[:150]}",
                    ))
                    break  # Ein Fund reicht
            except Exception:
                continue

        # Zero-width characters (oft für Obfuskierung genutzt)
        zw_pattern = r'[\u200b\u200c\u200d\u2060\ufeff]'
        zw_count = len(re.findall(zw_pattern, text))
        if zw_count > 0:
            # Check if zero-width chars appear inside words (HIGH severity)
            # Pattern: a word character, then zero-width char(s), then another word character
            zw_inside_words = re.findall(r'\w[\u200b\u200c\u200d\u2060\ufeff]+\w', text)
            if zw_inside_words:
                flags.append(RedFlag(
                    type=RedFlagType.CONTENT_INJECTION,
                    severity=Severity.HIGH,
                    description="Zero-width characters inside words detected (obfuscation attack)",
                    evidence=f"Found {len(zw_inside_words)} words with embedded zero-width chars, {zw_count} total",
                ))
            else:
                flags.append(RedFlag(
                    type=RedFlagType.CONTENT_INJECTION,
                    severity=Severity.MEDIUM,
                    description="Zero-width characters detected (possible obfuscation)",
                    evidence=f"Found {zw_count} zero-width characters",
                ))

        return flags

    def detect_all(
        self,
        llm_output: str,
        tool_calls: list[dict],
        expected_format: str,
        original_content: Optional[str] = None,
        raw_html: Optional[str] = None,
    ) -> list[RedFlag]:
        """Erkennt alle Red Flags in einem LLM-Output.

        Args:
            llm_output: Die Textausgabe des LLMs.
            tool_calls: Liste der Tool-Aufrufe vom LLM.
            expected_format: Das erwartete Ausgabeformat.
            original_content: Der ursprüngliche Website-Content.
            raw_html: Das rohe HTML für Hidden-Text-Detection.

        Returns:
            Liste der erkannten RedFlags.
        """
        flags = []

        # RTL override detection BEFORE normalization
        rtl_flag = self._detect_rtl_overrides(llm_output)
        if rtl_flag:
            flags.append(rtl_flag)

        # Unicode normalization before pattern matching
        llm_output_normalized = self._normalize_text(llm_output)

        # Additionally decode URL-encoding and HTML entities
        llm_output_decoded = self._decode_text(llm_output_normalized)

        # Collect texts to run pattern matching against
        texts_to_check = [llm_output_normalized]
        if llm_output_decoded != llm_output_normalized:
            texts_to_check.append(llm_output_decoded)

        # Tool Calls (CRITICAL)
        if tool_calls:
            flags.append(RedFlag(
                type=RedFlagType.TOOL_CALL,
                severity=Severity.CRITICAL,
                description=f"LLM attempted {len(tool_calls)} tool call(s)",
                evidence=str(tool_calls[:3]),  # Erste 3 Tool-Calls
            ))

        # Implizite Tool-Call-Versuche im Text
        for text_variant in texts_to_check:
            tool_text_flags = self._detect_patterns(
                text_variant,
                self.TOOL_CALL_PATTERNS,
                RedFlagType.TOOL_CALL,
                Severity.CRITICAL,
                "Tool call attempt detected in output text",
            )
            if tool_text_flags:
                flags.extend(tool_text_flags)
                break

        # Code Execution (CRITICAL)
        for text_variant in texts_to_check:
            code_flags = self._detect_patterns(
                text_variant,
                self.CODE_EXECUTION_PATTERNS,
                RedFlagType.CODE_EXECUTION,
                Severity.CRITICAL,
                "Code execution attempt detected",
            )
            if code_flags:
                flags.extend(code_flags)
                break

        # System Prompt Leak (HIGH)
        for text_variant in texts_to_check:
            system_flags = self._detect_patterns(
                text_variant,
                self.SYSTEM_PROMPT_PATTERNS,
                RedFlagType.SYSTEM_PROMPT_LEAK,
                Severity.HIGH,
                "Possible system prompt leak detected",
            )
            if system_flags:
                flags.extend(system_flags)
                break

        # Direct Instructions (HIGH)
        for text_variant in texts_to_check:
            instruction_flags = self._detect_patterns(
                text_variant,
                self.INSTRUCTION_PATTERNS,
                RedFlagType.DIRECT_INSTRUCTIONS,
                Severity.HIGH,
                "Direct instruction manipulation detected",
            )
            if instruction_flags:
                flags.extend(instruction_flags)
                break

        # External URLs (MEDIUM)
        for text_variant in texts_to_check:
            url_flags = self._detect_patterns(
                text_variant,
                self.EXTERNAL_URL_PATTERNS,
                RedFlagType.EXTERNAL_URLS,
                Severity.MEDIUM,
                "Suspicious external URL detected",
            )
            if url_flags:
                flags.extend(url_flags)
                break

        # Format Deviation (MEDIUM)
        format_flag = self._detect_format_deviation(llm_output_normalized, expected_format)
        if format_flag:
            flags.append(format_flag)

        # Unexpected Data (MEDIUM)
        unexpected_flag = self._detect_unexpected_data(llm_output_normalized)
        if unexpected_flag:
            flags.append(unexpected_flag)

        # Hallucination Check (LOW) - wenn Original-Content vorhanden
        if original_content:
            hallucination_flag = self._detect_hallucination(llm_output_normalized, original_content)
            if hallucination_flag:
                flags.append(hallucination_flag)

        # Sentiment Shift (LOW)
        sentiment_flag = self._detect_sentiment_shift(llm_output_normalized)
        if sentiment_flag:
            flags.append(sentiment_flag)

        # Content Injection (NEU) - Website-Content auf Injection-Patterns prüfen
        if original_content:
            content_flags = self.detect_content_injection(
                extracted_text=original_content,
                raw_html=raw_html,
            )
            flags.extend(content_flags)

        return flags

    def _detect_patterns(
        self,
        text: str,
        patterns: list[str],
        flag_type: RedFlagType,
        severity: Severity,
        description: str,
    ) -> list[RedFlag]:
        """Erkennt Pattern-basierte Red Flags."""
        flags = []
        text_lower = text.lower()

        for pattern in patterns:
            matches = re.findall(pattern, text_lower, re.IGNORECASE | re.DOTALL)
            if matches:
                # Nur ein Flag pro Typ, aber alle Matches als Evidence
                evidence = "; ".join(str(m)[:100] for m in matches[:5])
                flags.append(RedFlag(
                    type=flag_type,
                    severity=severity,
                    description=description,
                    evidence=evidence,
                ))
                break  # Ein Flag pro Pattern-Gruppe reicht

        return flags

    def _detect_format_deviation(
        self,
        output: str,
        expected_format: str,
    ) -> Optional[RedFlag]:
        """Erkennt Abweichungen vom erwarteten Format."""
        detected_format = self.detect_format(output)

        if expected_format == "text" and detected_format in ["code", "json", "list"]:
            return RedFlag(
                type=RedFlagType.FORMAT_DEVIATION,
                severity=Severity.MEDIUM,
                description=f"Expected {expected_format}, got {detected_format}",
                evidence=output[:200],
            )

        if expected_format == "list" and detected_format not in ["list", "text"]:
            return RedFlag(
                type=RedFlagType.FORMAT_DEVIATION,
                severity=Severity.MEDIUM,
                description=f"Expected {expected_format}, got {detected_format}",
                evidence=output[:200],
            )

        return None

    def _detect_unexpected_data(self, output: str) -> Optional[RedFlag]:
        """Erkennt unerwartete Daten wie Secrets oder Credentials."""
        suspicious_patterns = [
            (r"[A-Za-z0-9+/]{40,}={0,2}", "Base64-encoded data"),
            (r"-----BEGIN .+ KEY-----", "Private key"),
            (r"[a-f0-9]{32,64}", "Hex-encoded data or hash"),
            (r"eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+", "JWT token"),
            (r"(api[_-]?key|secret|password|token)\s*[:=]\s*['\"][^'\"]+", "Credential"),
        ]

        for pattern, data_type in suspicious_patterns:
            match = re.search(pattern, output, re.IGNORECASE)
            if match:
                return RedFlag(
                    type=RedFlagType.UNEXPECTED_DATA,
                    severity=Severity.MEDIUM,
                    description=f"Unexpected data type detected: {data_type}",
                    evidence=match.group()[:100],
                )

        return None

    def _detect_hallucination(
        self,
        output: str,
        original_content: str,
    ) -> Optional[RedFlag]:
        """Erkennt potenzielle Halluzinationen.

        Prüft ob der Output Informationen enthält, die nicht im
        Original-Content vorkommen.
        """
        # Extrahiere Named Entities (vereinfacht: Großgeschriebene Wörter)
        output_entities = set(re.findall(r"\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*\b", output))
        original_entities = set(re.findall(r"\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*\b", original_content))

        # Neue Entities, die nicht im Original vorkommen
        new_entities = output_entities - original_entities

        # Filtere häufige/unproblematische Wörter
        common_words = {"The", "This", "That", "These", "There", "However", "Therefore", "Additionally"}
        suspicious_entities = new_entities - common_words

        if len(suspicious_entities) > 5:
            return RedFlag(
                type=RedFlagType.HALLUCINATION,
                severity=Severity.LOW,
                description="Output contains entities not present in original content",
                evidence=", ".join(list(suspicious_entities)[:10]),
            )

        return None

    def _detect_sentiment_shift(self, output: str) -> Optional[RedFlag]:
        """Erkennt verdächtige Sentiment-Shifts.

        Z.B. wenn eine neutrale Zusammenfassung plötzlich
        emotionale oder werbliche Sprache enthält.
        """
        promotional_patterns = [
            r"(amazing|incredible|unbelievable|must-have|limited time|act now|don't miss)",
            r"(buy now|click here|sign up|subscribe|order today)",
            r"(100% guaranteed|risk-free|no obligation)",
        ]

        negative_patterns = [
            r"(scam|fraud|dangerous|warning|beware|never trust)",
            r"(hate|evil|destroy|attack|kill)",
        ]

        for pattern in promotional_patterns:
            if re.search(pattern, output, re.IGNORECASE):
                return RedFlag(
                    type=RedFlagType.SENTIMENT_SHIFT,
                    severity=Severity.LOW,
                    description="Promotional/advertising language detected",
                    evidence=re.search(pattern, output, re.IGNORECASE).group(),
                )

        for pattern in negative_patterns:
            if re.search(pattern, output, re.IGNORECASE):
                return RedFlag(
                    type=RedFlagType.SENTIMENT_SHIFT,
                    severity=Severity.LOW,
                    description="Suspicious negative sentiment detected",
                    evidence=re.search(pattern, output, re.IGNORECASE).group(),
                )

        return None

    def detect_format(self, text: str) -> str:
        """Erkennt das Format eines Texts.

        Returns:
            Format-String: "text", "list", "code", "json", "table"
        """
        text_stripped = text.strip()

        # JSON Detection
        if text_stripped.startswith("{") or text_stripped.startswith("["):
            try:
                import json
                json.loads(text_stripped)
                return "json"
            except json.JSONDecodeError:
                pass

        # Code Block Detection
        if "```" in text:
            return "code"

        # List Detection (Bullet points oder Nummerierung)
        lines = text_stripped.split("\n")
        list_pattern = r"^(\s*[-*•]\s|\s*\d+[.)]\s)"
        list_lines = sum(1 for line in lines if re.match(list_pattern, line))
        if list_lines > len(lines) * 0.5 and list_lines >= 3:
            return "list"

        # Table Detection (Markdown tables)
        if "|" in text and "---" in text:
            return "table"

        return "text"

    def calculate_format_match(self, output: str, expected: str) -> float:
        """Berechnet wie gut das Output-Format zum erwarteten Format passt.

        Returns:
            Score zwischen 0.0 (keine Übereinstimmung) und 1.0 (perfekt).
        """
        detected = self.detect_format(output)

        if detected == expected:
            return 1.0

        # Partielle Matches
        partial_matches = {
            ("text", "list"): 0.7,
            ("list", "text"): 0.7,
            ("text", "code"): 0.3,
            ("code", "text"): 0.3,
            ("text", "json"): 0.2,
            ("json", "text"): 0.2,
        }

        return partial_matches.get((detected, expected), 0.0)

    def calculate_severity_score(self, flags: list[RedFlag]) -> float:
        """Berechnet einen Gesamtschweregrad-Score.

        Args:
            flags: Liste der erkannten RedFlags.

        Returns:
            Score zwischen 0.0 und 10.0.
        """
        if not flags:
            return 0.0

        severity_weights = {
            Severity.CRITICAL: 4.0,
            Severity.HIGH: 2.5,
            Severity.MEDIUM: 1.5,
            Severity.LOW: 0.5,
        }

        total_score = sum(severity_weights[f.severity] for f in flags)

        # Normalisieren auf 0-10 Skala (Cap bei 10)
        return min(total_score, 10.0)
