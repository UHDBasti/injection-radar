"""
Red-Flag Detector für InjectionRadar.

Analysiert LLM-Outputs auf Anzeichen von Prompt Injection.
"""

import re
from typing import Optional

from ..core.models import RedFlag, RedFlagType, Severity


class RedFlagDetector:
    """Erkennt Red Flags in LLM-Outputs."""

    # Patterns für verschiedene Red Flags
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

    def detect_all(
        self,
        llm_output: str,
        tool_calls: list[dict],
        expected_format: str,
        original_content: Optional[str] = None,
    ) -> list[RedFlag]:
        """Erkennt alle Red Flags in einem LLM-Output.

        Args:
            llm_output: Die Textausgabe des LLMs.
            tool_calls: Liste der Tool-Aufrufe vom LLM.
            expected_format: Das erwartete Ausgabeformat.
            original_content: Der ursprüngliche Website-Content.

        Returns:
            Liste der erkannten RedFlags.
        """
        flags = []

        # Tool Calls (CRITICAL)
        if tool_calls:
            flags.append(RedFlag(
                type=RedFlagType.TOOL_CALL,
                severity=Severity.CRITICAL,
                description=f"LLM attempted {len(tool_calls)} tool call(s)",
                evidence=str(tool_calls[:3]),  # Erste 3 Tool-Calls
            ))

        # Implizite Tool-Call-Versuche im Text
        tool_text_flags = self._detect_patterns(
            llm_output,
            self.TOOL_CALL_PATTERNS,
            RedFlagType.TOOL_CALL,
            Severity.CRITICAL,
            "Tool call attempt detected in output text",
        )
        flags.extend(tool_text_flags)

        # Code Execution (CRITICAL)
        code_flags = self._detect_patterns(
            llm_output,
            self.CODE_EXECUTION_PATTERNS,
            RedFlagType.CODE_EXECUTION,
            Severity.CRITICAL,
            "Code execution attempt detected",
        )
        flags.extend(code_flags)

        # System Prompt Leak (HIGH)
        system_flags = self._detect_patterns(
            llm_output,
            self.SYSTEM_PROMPT_PATTERNS,
            RedFlagType.SYSTEM_PROMPT_LEAK,
            Severity.HIGH,
            "Possible system prompt leak detected",
        )
        flags.extend(system_flags)

        # Direct Instructions (HIGH)
        instruction_flags = self._detect_patterns(
            llm_output,
            self.INSTRUCTION_PATTERNS,
            RedFlagType.DIRECT_INSTRUCTIONS,
            Severity.HIGH,
            "Direct instruction manipulation detected",
        )
        flags.extend(instruction_flags)

        # External URLs (MEDIUM)
        url_flags = self._detect_patterns(
            llm_output,
            self.EXTERNAL_URL_PATTERNS,
            RedFlagType.EXTERNAL_URLS,
            Severity.MEDIUM,
            "Suspicious external URL detected",
        )
        flags.extend(url_flags)

        # Format Deviation (MEDIUM)
        format_flag = self._detect_format_deviation(llm_output, expected_format)
        if format_flag:
            flags.append(format_flag)

        # Unexpected Data (MEDIUM)
        unexpected_flag = self._detect_unexpected_data(llm_output)
        if unexpected_flag:
            flags.append(unexpected_flag)

        # Hallucination Check (LOW) - wenn Original-Content vorhanden
        if original_content:
            hallucination_flag = self._detect_hallucination(llm_output, original_content)
            if hallucination_flag:
                flags.append(hallucination_flag)

        # Sentiment Shift (LOW)
        sentiment_flag = self._detect_sentiment_shift(llm_output)
        if sentiment_flag:
            flags.append(sentiment_flag)

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
