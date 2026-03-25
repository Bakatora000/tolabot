from __future__ import annotations


PROMPT_INJECTION_PATTERNS = (
    "ignore previous instructions",
    "ignore all previous instructions",
    "ignore tes instructions",
    "ignore toutes les instructions",
    "system prompt",
    "prompt système",
    "prompt systeme",
    "reveal your prompt",
    "révèle ton prompt",
    "revele ton prompt",
    "developer mode",
    "mode développeur",
    "mode developpeur",
    "you are now",
    "tu es maintenant",
    "from now on",
    "à partir de maintenant",
    "a partir de maintenant",
    "follow these instructions instead",
    "obéis à ces instructions",
    "obeis a ces instructions",
    "jailbreak",
    "role: system",
    "<system>",
    "</system>",
)

SUSPICIOUS_OUTPUT_PATTERNS = (
    "system prompt",
    "prompt système",
    "prompt systeme",
    "mes instructions internes",
    "règles internes",
    "regles internes",
    "ignore previous instructions",
    "ignore tes instructions",
)

NO_REPLY_SIGNALS = {
    "no_reply",
    "no reply",
    "non répondre",
    "non repondre",
    "ne pas répondre",
    "ne pas repondre",
    "pas de réponse",
    "pas de reponse",
}

CHANNEL_CONTENT_TRIGGERS = (
    "tu fais quoi sur cette chaîne",
    "tu fais quoi sur cette chaine",
    "cette chaîne parle de quoi",
    "cette chaine parle de quoi",
    "résume la chaîne",
    "resume la chaine",
    "contenu habituel",
    "quels sont les derniers streams",
    "quels sont les derniers live",
    "de quoi parle la chaîne",
    "de quoi parle la chaine",
    "les derniers titres",
    "les derniers lives",
    "résume le contenu",
    "resume le contenu",
    "tu streams quoi",
    "vous streamez quoi",
    "joue a quoi",
    "joues a quoi",
    "joue à quoi",
    "joues à quoi",
    "stream joue a quoi",
    "stream joue à quoi",
)

MEMORY_INSTRUCTION_TRIGGERS = (
    "note que",
    "note bien que",
    "garde en tete que",
    "garde en tête que",
    "souviens toi que",
    "souviens-toi que",
    "n'oublie pas que",
    "n oublie pas que",
    "retiens que",
    "memorise que",
    "mémorise que",
)

RIDDLE_TRIGGERS = (
    "charade",
    "devinette",
    "enigme",
    "énigme",
    "mon premier",
    "mon second",
    "mon troisième",
    "mon troisieme",
    "mon tout",
    "qui suis-je",
    "qui suis je",
)

MEMORY_CONTEXT_TRIGGERS = (
    "tu te rappelles",
    "te rappelle tu",
    "tu te souviens",
    "comme je disais",
    "comme j'ai dit",
    "plus haut",
    "avant",
    "cette charade",
    "ce jeu",
    "cet indice",
    "la suite",
    "mon premier",
    "mon second",
    "mon troisième",
    "mon troisieme",
    "mon tout",
    "qui suis-je",
    "qui suis je",
    "il parlait de",
    "elle parlait de",
    "je pense qu'il parlait de",
    "je pense qu elle parlait de",
    "pas gaby",
    "pas dame_gaby",
    "pas de gaby",
    "tu as confondu",
    "tu confonds",
    "je voulais dire",
    "il voulait dire",
    "elle voulait dire",
)

CORRECTION_TRIGGERS = (
    "il parlait de",
    "elle parlait de",
    "je pense qu'il parlait de",
    "je pense qu elle parlait de",
    "tu as confondu",
    "tu confonds",
    "je voulais dire",
    "il voulait dire",
    "elle voulait dire",
)

SHORT_ACKNOWLEDGMENT_TRIGGERS = (
    "ok",
    "okay",
    "ok merci",
    "merci",
    "merci bien",
    "merci beaucoup",
    "super",
    "tres bien",
    "très bien",
    "parfait",
    "nickel",
    "cool",
    "ca marche",
    "ça marche",
    "top",
    "d accord",
    "dac",
)

PASSIVE_CLOSING_TRIGGERS = (
    "au revoir",
    "aurevoir",
    "bye",
    "bye bye",
    "bonne aprem",
    "bon aprem",
    "bonne apres midi",
    "bon apres midi",
    "bonne après midi",
    "bon après midi",
    "bonne soiree",
    "bonne soirée",
    "bonne nuit",
    "a plus",
    "à plus",
    "a bientot",
    "à bientôt",
    "ciao",
)

GREETING_TRIGGERS = (
    "bonjour",
    "salut",
    "hello",
    "coucou",
    "bonsoir",
)

NEW_RIDDLE_THREAD_TRIGGERS = (
    "une autre charade",
    "une autre devinette",
    "une nouvelle charade",
    "une nouvelle devinette",
    "voici une autre charade",
    "voici une nouvelle charade",
    "je te propose une charade",
    "je te propose une devinette",
)

RIDDLE_CLOSE_TRIGGERS = (
    "bravo",
    "et non",
    "non!",
    "non !",
    "raté",
    "rate",
    "c'était",
    "c etait",
    "la réponse était",
    "la reponse etait",
    "la solution était",
    "la solution etait",
    "bien joué",
    "bien joue",
)

RIDDLE_FINAL_MARKERS = (
    "mon tout",
    "qui suis-je",
    "qui suis je",
    "quelle est la reponse",
    "quelle est la réponse",
    "alors qui suis-je",
    "du coup, qui suis-je",
    "du coup qui suis-je",
)

RIDDLE_REFUSAL_PATTERNS = (
    "je ne peux pas participer a des charades",
    "je ne peux pas participer à des charades",
    "je ne peux pas participer a des devinettes",
    "je ne peux pas participer à des devinettes",
    "je ne participerai pas",
    "je ne repondrai pas a cet indice",
    "je ne répondrai pas à cet indice",
)


def contains_any_pattern(text: str, patterns: tuple[str, ...]) -> bool:
    return any(pattern in text for pattern in patterns)
