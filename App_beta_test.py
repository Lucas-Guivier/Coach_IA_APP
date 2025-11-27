import streamlit as st
import time
import json
from neo4j import GraphDatabase
from openai import OpenAI
from string import Template

GRAPH_TAG = "kg-label-v1"
NEO4J_DB = "neo4j"

# ========================= 1. CONFIGURATION & DESIGN =========================

st.set_page_config(page_title="Coach IA Hybride", page_icon="⚡️", layout="centered")

# --- CSS PERSONNALISÉ ---
st.markdown("""
    <style>
        /* Import des polices : Teko (titres) + Nunito (texte) */
        @import url('https://fonts.googleapis.com/css2?family=Teko:wght@400;500;600&family=Nunito:wght@300;400;600&display=swap');

        /* Police par défaut pour tout le texte (Nunito) */
        html, body, [class*="css"]  {
            font-family: 'Nunito', system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
        }

        /* Titres façon "coach" (Teko) */
        h1, h2, h3 {
            font-family: 'Teko', 'Impact', system-ui, sans-serif;
            letter-spacing: 0.03em;
        }

        /* Gros message d’intro (machine à écrire) */
        .intro-typing {
            font-family: 'Teko', 'Impact', system-ui, sans-serif;
            font-size: 2.2rem;
            font-weight: 500;
            line-height: 1.1;
            text-transform: uppercase;
        }

        /* Boutons : look un peu plus sportif */
        .stButton>button {
            border-radius: 8px;
            font-weight: 600;
            height: 3em;
            font-family: 'Teko', 'Impact', system-ui, sans-serif;
            letter-spacing: 0.04em;
        }

        #MainMenu {visibility: hidden;}
        footer {visibility: hidden;}
    </style>
""", unsafe_allow_html=True)

# --- SIDEBAR AVEC LOGO ---
with st.sidebar:
    # Pas de logo pour le moment, juste un footer propre
    st.markdown("---")
    st.caption("v3.0 • Powered by Neo4j & OpenAI")

if "page" not in st.session_state:
    st.session_state.page = "onboarding"
if "user_profile" not in st.session_state:
    st.session_state.user_profile = {}
if "last_feedback" not in st.session_state:
    st.session_state.last_feedback = None
if "workout_plan" not in st.session_state:
    st.session_state.workout_plan = None
if "session_time" not in st.session_state:
    st.session_state.session_time = 30
if "sessions_done" not in st.session_state:
    st.session_state.sessions_done = 0

# --- Onboarding multi-étapes ---
if "onboarding_step" not in st.session_state:
    st.session_state.onboarding_step = "intro"  # intro -> goals -> equipment -> schedule_pain -> loading -> summary

if "intro_typed" not in st.session_state:
    st.session_state.intro_typed = False
if "typed_goals" not in st.session_state:
    st.session_state.typed_goals = False
if "typed_equipment" not in st.session_state:
    st.session_state.typed_equipment = False
if "typed_schedule_pain" not in st.session_state:
    st.session_state.typed_schedule_pain = False

# Stockage temporaire des réponses onboarding
if "onb_goals" not in st.session_state:
    st.session_state.onb_goals = ""
if "onb_equipment" not in st.session_state:
    st.session_state.onb_equipment = ""
if "onb_sessions_per_week" not in st.session_state:
    st.session_state.onb_sessions_per_week = 3
if "onb_pain" not in st.session_state:
    st.session_state.onb_pain = ""

# Pour la confirmation du profil
if "summary_needs_correction" not in st.session_state:
    st.session_state.summary_needs_correction = False
if "summary_correction_note" not in st.session_state:
    st.session_state.summary_correction_note = ""

# --- CHARGEMENT DES SECRETS ---
try:
    NEO4J_URI = st.secrets["NEO4J_URI"]
    NEO4J_USER = st.secrets["NEO4J_USER"]
    NEO4J_PASSWORD = st.secrets["NEO4J_PASSWORD"]
    OPENAI_API_KEY = st.secrets["OPENAI_API_KEY"]
    OPENAI_BASE_URL = "https://openrouter.ai/api/v1"
except Exception as e:
    st.error(f"❌ Erreur de configuration des secrets : {e}")
    st.stop()

# ========================= 2. DONNÉES DE RÉFÉRENCE =========================

INJURY_KEYS = [
    "Mal de dos (Lombaires)",
    "Genoux",
    "Épaules",
    "Hanches",
    "Cou / Cervicales",
    "Aucune",
]

INJURY_MAP = {
    "Mal de dos (Lombaires)": ["spine", "lumbar", "vertebrae", "erector", "back"],
    "Genoux": ["knee", "patella", "meniscus"],
    "Épaules": ["rotator", "shoulder", "deltoid"],
    "Hanches": ["hip", "gluteus", "pelvis", "piriformis"],
    "Cou / Cervicales": ["cervical", "neck", "trapezius"],
    "Aucune": [],
}

EQUIPMENT_KEYS = [
    "Barbell", "Dumbbell", "Kettlebell", "Machine", "Cable",
    "Bench", "Pull-up Bar", "Treadmill", "Rower", "Bands",
    "Foam Roll", "Bodyweight"
]

INTRO_TEXT = (
    "Bienvenue, je suis ton coach. Je t'aiderai à atteindre tes objectifs. "
    "Avant de commencer, dis-moi quelques informations sur toi."
)

EXPERIENCE_CHOICES = {
    "🍼 Je viens de commencer": "Beginner",
    "🌱 Moins de 6 mois": "Beginner",
    "🏋️ De 6 mois à 2 ans": "Intermediate",
    "🦾 De 2 à 5 ans": "Intermediate",
    "🧠 Depuis plus de 5 ans": "Advanced",
}

def typewriter(text: str, speed: float = 0.03):
    """Affiche un texte lettre par lettre (effet machine à écrire) avec la classe intro-typing (Teko)."""
    placeholder = st.empty()
    out = ""
    for ch in text:
        out += ch
        placeholder.markdown(
            f'<p class="intro-typing">{out}</p>',
            unsafe_allow_html=True
        )
        time.sleep(speed)

# ========================= 3. RESSOURCES PARTAGÉES (CACHE) =========================

@st.cache_resource
def get_openai_client():
    return OpenAI(api_key=OPENAI_API_KEY, base_url=OPENAI_BASE_URL)

@st.cache_resource
def get_neo4j_driver():
    return GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))

# ========================= 4. MOTEUR INTELLIGENT (BACKEND) =========================

def extract_profile_from_text(bio_text: str):
    """
    Transforme le langage naturel en données structurées pour le Graphe.
    Retourne un dict : {"equipment": [...], "injuries": [...], "goals": [...]}
    """
    client = get_openai_client()

    system_msg = (
        "Tu es un Analyste de Données Sportives. "
        "Tu lis le texte d'un client et tu en extrais des informations structurées. "
        "Tu renvoies UNIQUEMENT du JSON valide avec les champs : 'equipment', 'injuries', 'goals', "
        "chacun étant une liste de chaînes."
    )

    user_msg = f"""
TEXTE UTILISATEUR : "{bio_text}"

1. MATÉRIEL (Liste exacte parmi : {', '.join(EQUIPMENT_KEYS)}).
   - Si l'utilisateur dit 'rien', 'aucun matériel', ou 'maison', mets ["Bodyweight"].
   - Si l'utilisateur dit 'salle de sport', mets tous les éléments disponibles : {', '.join(EQUIPMENT_KEYS)}.

2. BLESSURES (Liste exacte parmi : {', '.join(INJURY_KEYS)}).
   - Si aucune mention, mets ["Aucune"].

3. OBJECTIFS (Synthèse courte sous forme de quelques mots, ex: "Perte de gras", "Prise de muscle", "Mobilité", etc.).
   - Mets ces objectifs dans une liste de chaînes, ex: ["Perte de gras", "Renforcement dos"].

RENVOIE UNIQUEMENT DU JSON AVEC :
{{
  "equipment": [...],
  "injuries": [...],
  "goals": [...]
}}
"""

    try:
        resp = client.chat.completions.create(
            model="openai/gpt-4o-mini",
            messages=[
                {"role": "system", "content": system_msg},
                {"role": "user", "content": user_msg},
            ],
            temperature=0,
            response_format={"type": "json_object"},
        )
        data = json.loads(resp.choices[0].message.content)
        # Sécurisation minimale
        equipment = data.get("equipment") or ["Bodyweight"]
        injuries = data.get("injuries") or ["Aucune"]
        goals = data.get("goals") or ["Forme"]
        return {
            "equipment": equipment,
            "injuries": injuries,
            "goals": goals,
        }
    except Exception as e:
        st.error(f"Erreur d'analyse du profil IA : {e}")
        return {"equipment": ["Bodyweight"], "injuries": ["Aucune"], "goals": ["Forme"]}


def get_safe_exercises(profile: dict, context: dict):
    """
    Interroge Neo4j pour trouver les exercices compatibles ET leurs vidéos.
    Filtré par matériel + zones à éviter (blessures + douleurs du jour).
    """
    driver = get_neo4j_driver()

    banned_terms = []
    pain_points = (profile.get("injuries") or []) + (context.get("daily_pain") or [])
    for injury in pain_points:
        banned_terms.extend(INJURY_MAP.get(injury, []))

    user_equip = [eq.lower() for eq in profile.get("equipment", [])] + ["none", "bodyweight"]

    query = """
    MATCH (e:Exercise)
    WHERE e.graph_tag = $graph_tag
      AND toLower(e.equipment) IN $equipment
      AND ALL(sec IN coalesce(e.equipment_secondary, ['none'])
              WHERE toLower(sec) IN $equipment OR toLower(sec) = 'none')
      AND NOT EXISTS {
          MATCH (e)-[:TARGETS]->(b:BodyPart)
          WHERE any(term IN $banned_terms WHERE toLower(b.name) CONTAINS term)
      }
    RETURN DISTINCT e.name AS name, e.video AS video
    LIMIT 40
    """

    try:
        with driver.session(database=NEO4J_DB) as session:
            res = session.run(
                query,
                {
                    "equipment": user_equip,
                    "banned_terms": [t.lower() for t in banned_terms],
                    "graph_tag": GRAPH_TAG,
                },
            )
            return [{"name": r["name"], "video": r["video"]} for r in res]
    except Exception as e:
        st.error(f"Erreur Neo4j : {e}")
        return []


def generate_session_with_llm(profile: dict, context: dict, valid_exercises: list, last_feedback: dict | None):
    """
    Génére une séance structurée au format JSON :
    {
      "strategie": [...],
      "seance": {
         "echauffement": [...],
         "corps": [...],
         "retour_calme": [...]
      },
      "mot_fin": "..."
    }
    Chaque exercice contient :
      - name (string)
      - sets (int ou null)
      - reps (string ou null)
      - duration_min (int ou null)
      - video (string ou null)
      - instruction (string)
    """
    client = get_openai_client()

    safe_exos_min = [
        {"name": ex["name"], "video": ex.get("video")}
        for ex in valid_exercises
    ]

    feedback_json = last_feedback or {}

    system_msg = (
        "Tu es un coach sportif d'élite. "
        "Tu construis des séances personnalisées basées sur des exercices sécurisés fournis. "
        "Tu dois impérativement renvoyer UNIQUEMENT du JSON valide (aucun texte autour) avec la structure suivante : "
        "strategie (liste de phrases), seance.echauffement/corps/retour_calme (listes d'exercices), mot_fin (string). "
        "Chaque exercice contient les clés : name, sets, reps, duration_min, video, instruction."
    )

    user_msg = (
        "INFOS CLIENT :\n"
        f"- Âge : {profile.get('age')}\n"
        f"- Niveau : {profile.get('level')}\n"
        f"- Objectifs : {', '.join(profile.get('goals', []))}\n"
        f"- Matériel disponible : {', '.join(profile.get('equipment', []))}\n"
        f"- Contraintes santé (profil) : {', '.join(profile.get('injuries', []))}\n\n"
        "CONTEXTE JOURNALIER :\n"
        f"- Énergie du jour (1-10) : {context.get('energy')}\n"
        f"- Temps disponible (minutes) : {context.get('time')}\n"
        f"- Douleurs du jour : {', '.join(context.get('daily_pain', []))}\n"
        f"- Message libre de la personne : \"{context.get('note', '')}\"\n\n"
        "DERNIER FEEDBACK DE SÉANCE (JSON) :\n"
        f"{json.dumps(feedback_json, ensure_ascii=False)}\n\n"
        "EXERCICES SÉCURISÉS DISPONIBLES (tu ne dois utiliser que des exercices issus de cette liste) :\n"
        f"{json.dumps(safe_exos_min, ensure_ascii=False)}\n\n"
        "TA MISSION :\n"
        "1. Construire une séance cohérente et sécurisée en 3 parties : échauffement, corps de séance, retour au calme.\n"
        "2. Adapter l'intensité et le volume en fonction du niveau, de l'énergie du jour, des douleurs, du feedback précédent et du temps disponible.\n"
        "3. Pour chaque exercice utilisé, le choisir dans la liste fournie et renvoyer un objet avec :\n"
        "   - name (string)\n"
        "   - sets (int ou null)\n"
        "   - reps (string ou null)\n"
        "   - duration_min (int ou null)\n"
        "   - video (string ou null)\n"
        "   - instruction (string en français, clair et rassurant).\n\n"
        "FORMAT DE RÉPONSE :\n"
        "Renvoyer UNIQUEMENT du JSON avec les clés :\n"
        "- strategie: liste de 2 à 4 phrases expliquant l'adaptation de la séance\n"
        "- seance: objet avec les clés 'echauffement', 'corps', 'retour_calme' (chacune une liste d'exercices)\n"
        "- mot_fin: une phrase courte de conclusion positive en français.\n"
    )

    try:
        resp = client.chat.completions.create(
            model="openai/gpt-4o-mini",
            messages=[
                {"role": "system", "content": system_msg},
                {"role": "user", "content": user_msg},
            ],
            temperature=0.5,
            response_format={"type": "json_object"},
        )
        content = resp.choices[0].message.content
        plan = json.loads(content)
        return plan
    except Exception as e:
        st.error(f"Erreur lors de la génération de la séance IA : {e}")
        return None

# ========================= 5. PAGES DE L'APPLICATION =========================

def page_onboarding():
    step = st.session_state.onboarding_step

    # ========= ÉTAPE 0 : Intro (même logique qu'avant) =========
    if step == "intro":
        st.empty()  # page clean

        if not st.session_state.intro_typed:
            typewriter(INTRO_TEXT)
            st.session_state.intro_typed = True
        else:
            st.markdown(
                f'<p class="intro-typing">{INTRO_TEXT}</p>',
                unsafe_allow_html=True
            )

        st.markdown("")

        with st.form("intro_form"):
            c1, c2 = st.columns(2)
            with c1:
                age = st.number_input("Quel âge as-tu ?", 18, 90, 30)
            with c2:
                exp_label = st.selectbox(
                    "Depuis combien de temps tu fais du sport régulièrement ?",
                    list(EXPERIENCE_CHOICES.keys()),
                )

            submitted = st.form_submit_button("Suivant ➜")
            if submitted:
                level_eng = EXPERIENCE_CHOICES[exp_label]
                st.session_state.user_profile = {
                    "age": age,
                    "level": level_eng,
                    "equipment": [],
                    "injuries": [],
                    "goals": [],
                }
                st.session_state.onboarding_step = "goals"
                st.rerun()

    # ========= ÉTAPE 1 : Objectifs =========
    elif step == "goals":
        if not st.session_state.typed_goals:
            typewriter("Présente-toi — Tout d'abord, donne-moi tes objectifs dans le sport.")
            st.session_state.typed_goals = True
        else:
            st.markdown(
                '<p class="intro-typing">Présente-toi — Tout d\'abord, donne-moi tes objectifs dans le sport.</p>',
                unsafe_allow_html=True
            )

        st.markdown(
            """
Tu peux parler de prise de muscle, perte de gras, cardio, santé, performance, etc.

> ℹ️ Pour l'instant, je peux te coacher uniquement sur la **musculation** et le **cardio**.  
> Les autres sports (sports collectifs, arts martiaux, etc.) ne sont pas encore disponibles.
"""
        )

        goals = st.text_area(
            "Quels sont tes objectifs dans le sport ?",
            height=200,
            value=st.session_state.onb_goals,
            placeholder="Ex : Je veux prendre du muscle, perdre un peu de ventre et améliorer mon cardio pour être moins essoufflé."
        )

        if st.button("Suivant ➜"):
            if len(goals.strip()) < 10:
                st.warning("Dis-m'en un peu plus sur tes objectifs pour que je puisse te suivre correctement 🙏")
            else:
                st.session_state.onb_goals = goals
                st.session_state.onboarding_step = "equipment"
                st.rerun()

    # ========= ÉTAPE 2 : Matériel =========
    elif step == "equipment":
        if not st.session_state.typed_equipment:
            typewriter("Parlons matériel — De quoi disposes-tu pour t'entraîner ?")
            st.session_state.typed_equipment = True
        else:
            st.markdown(
                "<p class=\"intro-typing\">Parlons matériel — De quoi disposes-tu pour t'entraîner ?</p>",
                unsafe_allow_html=True
            )

        st.markdown(
            """
Donne-moi le plus de détails possibles :

- Ce que tu as chez toi (ex : 1 haltère de 10 kg, élastiques, tapis…)  
- Si tu es à la salle, dis-moi si tu as **tout le matériel nécessaire** ou si certaines machines manquent.
"""
        )

        equipment = st.text_area(
            "Quel matériel as-tu pour t'entraîner ?",
            height=200,
            value=st.session_state.onb_equipment,
            placeholder="Ex : Je n'ai qu'un haltère de 10 kg et un tapis. À la salle, j'ai accès aux machines poids libres et poulies."
        )

        col1, col2 = st.columns([1, 1])
        with col1:
            if st.button("⬅️ Retour", use_container_width=True):
                st.session_state.onboarding_step = "goals"
                st.rerun()
        with col2:
            if st.button("Suivant ➜", use_container_width=True):
                if len(equipment.strip()) < 5:
                    st.warning("Dis-m'en un peu plus sur ton matériel pour que je puisse choisir les bons exercices 🙏")
                else:
                    st.session_state.onb_equipment = equipment
                    st.session_state.onboarding_step = "schedule_pain"
                    st.rerun()

    # ========= ÉTAPE 3 : Séances / Douleurs =========
    elif step == "schedule_pain":
        if not st.session_state.typed_schedule_pain:
            typewriter("Dernières questions — Ta fréquence et tes douleurs éventuelles.")
            st.session_state.typed_schedule_pain = True
        else:
            st.markdown(
                "<p class=\"intro-typing\">Dernières questions — Ta fréquence et tes douleurs éventuelles.</p>",
                unsafe_allow_html=True
            )

        st.markdown("### Combien de séances par semaine souhaites-tu faire ?")
        sessions = st.slider(
            "Séances par semaine",
            min_value=1,
            max_value=7,
            value=st.session_state.onb_sessions_per_week,
        )

        st.markdown("### As-tu des douleurs ou des blessures ?")
        pain = st.text_area(
            "Dis-moi tout ce qui est important à savoir (douleurs, blessures, zones à protéger).",
            height=150,
            value=st.session_state.onb_pain,
            placeholder="Ex : légère douleur au genou droit en descente d'escalier, mal au bas du dos quand je reste assis longtemps."
        )

        st.markdown("---")
        st.markdown("**Création du profil**")

        col1, col2 = st.columns([1, 1])
        with col1:
            if st.button("⬅️ Retour", use_container_width=True, key="back_schedule"):
                st.session_state.onboarding_step = "equipment"
                st.rerun()
        with col2:
            if st.button("Lancer la création du profil ➜", use_container_width=True):
                st.session_state.onb_sessions_per_week = sessions
                st.session_state.onb_pain = pain
                st.session_state.onboarding_step = "loading"
                st.rerun()

    # ========= ÉTAPE 4 : Chargement du profil =========
    elif step == "loading":
        st.title("Chargement du profil de suivi...")

        st.markdown("Je réfléchis à ton profil, à tes objectifs et à tes contraintes pour te suivre au mieux.")

        with st.spinner("Analyse de ton profil..."):
            goals = st.session_state.onb_goals
            equipment = st.session_state.onb_equipment
            sessions = st.session_state.onb_sessions_per_week
            pain = st.session_state.onb_pain

            bio_text = (
                f"Objectifs sportifs : {goals}\n"
                f"Matériel disponible : {equipment}\n"
                f"Séances souhaitées par semaine : {sessions}\n"
                f"Douleurs / blessures : {pain}\n"
            )

            data = extract_profile_from_text(bio_text)

            base_profile = st.session_state.user_profile or {}
            base_profile["equipment"] = data["equipment"]
            base_profile["injuries"] = data["injuries"]
            base_profile["goals"] = data["goals"]
            base_profile["sessions_per_week"] = sessions
            st.session_state.user_profile = base_profile

            st.session_state.profile_analysis = data

            time.sleep(1.0)

        st.session_state.onboarding_step = "summary"
        st.rerun()

    # ========= ÉTAPE 5 : Résumé + confirmation =========
    elif step == "summary":
        st.title("Ton profil est prêt ✅")

        p = st.session_state.user_profile
        data = st.session_state.get("profile_analysis", {})

        st.markdown(
            f"""
**Récap de ce que j'ai compris :**

- 🧑 **Âge :** {p.get('age', '-')} ans  
- ⏱️ **Expérience d'entraînement :** {p.get('level', '-')}  
- 🎯 **Objectifs :** {', '.join(data.get('goals', [])) or '—'}  
- 🎒 **Matériel :** {', '.join(data.get('equipment', [])) or '—'}  
- 🚑 **Points de vigilance :** {', '.join(data.get('injuries', [])) or '—'}  
- 📆 **Séances par semaine souhaitées :** {p.get('sessions_per_week', '—')}
"""
        )

        st.markdown("---")
        st.subheader("Peux-tu me confirmer que ça te ressemble ?")

        col1, col2 = st.columns(2)
        with col1:
            if st.button("Oui, c'est bon ✅", use_container_width=True):
                # Reset des états d'onboarding
                st.session_state.onboarding_step = "intro"
                st.session_state.intro_typed = False
                st.session_state.typed_goals = False
                st.session_state.typed_equipment = False
                st.session_state.typed_schedule_pain = False
                st.session_state.summary_needs_correction = False
                st.session_state.summary_correction_note = ""

                st.session_state.page = "checkin"
                st.rerun()

        with col2:
            if st.button("Non, quelque chose ne va pas ❌", use_container_width=True):
                st.session_state.summary_needs_correction = True

        if st.session_state.summary_needs_correction:
            st.markdown("### Dis-moi ce qui ne va pas")
            note = st.text_area(
                "Explique ce qui ne correspond pas à ta situation, je l'utiliserai pour corriger ton suivi.",
                height=150,
                value=st.session_state.summary_correction_note,
            )

            if st.button("Enregistrer et commencer mon entraînement 2.0 🚀", use_container_width=True):
                st.session_state.summary_correction_note = note

                # (Pour l'instant on ne réanalyse pas automatiquement, on stocke juste la remarque)
                st.session_state.onboarding_step = "intro"
                st.session_state.intro_typed = False
                st.session_state.typed_goals = False
                st.session_state.typed_equipment = False
                st.session_state.typed_schedule_pain = False

                st.session_state.page = "checkin"
                st.rerun()

def page_home():
    st.title("Ton QG 🏠")

    # Sécurité : s'il n'y a pas de profil, retour à l'onboarding
    if not st.session_state.user_profile:
        st.warning("Ton profil n'est pas encore configuré.")
        if st.button("Faire l'onboarding maintenant"):
            st.session_state.page = "onboarding"
            st.rerun()
        return

    p = st.session_state.user_profile

    with st.expander("Voir / modifier mon profil"):
        st.write(f"**Âge :** {p.get('age', '-')}")
        st.write(f"**Niveau :** {p.get('level', '-')}")
        st.write(f"**Objectifs :** {', '.join(p.get('goals', []))}")
        st.write(f"**Matériel :** {', '.join(p.get('equipment', []))}")
        st.write(f"**Vigilance :** {', '.join(p.get('injuries', []))}")
        if st.button("Refaire l'onboarding"):
            st.session_state.page = "onboarding"
            st.rerun()

    if st.session_state.sessions_done > 0:
        st.info(f"📈 Tu as déjà complété **{st.session_state.sessions_done}** séance(s) avec le coach.")

    if st.session_state.last_feedback:
        fb = st.session_state.last_feedback
        if isinstance(fb, dict):
            ressenti = fb.get("ressenti", "—")
            msg = fb.get("message", "")
            st.success(
                f"💡 **Mémoire du Coach :** dernière séance perçue comme **{ressenti}**. "
                f"Note : *{msg or '—'}*"
            )
        else:
            st.success(f"💡 **Mémoire du Coach :** *{fb}*")

    st.markdown("---")
    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        if st.button("LANCER MA SÉANCE 🔥", type="primary", use_container_width=True):
            st.session_state.page = "checkin"
            st.rerun()


def page_checkin():
    st.title("📍 Condition de mon entraînement")
    st.caption("Je vais adapter la séance à ton état réel du moment.")

    with st.form("checkin"):
        time_avail = st.slider(
        "⏱ Temps disponible (minutes)",
        min_value=15,
        max_value=90,
        step=5,
        value=30,
    )
        energy = st.slider("⚡️ Niveau d'énergie (1 = HS, 10 = On fire)", 1, 10, 6)
        
        st.markdown("**Douleur spécifique aujourd'hui ?** (en plus de ton profil habituel)")
        daily_pain = st.multiselect("Zone", list(INJURY_MAP.keys()), default=["Aucune"])
        
        note = st.text_input("Un message pour ton coach ? (mal dormi, stress, etc.)", value="")
        
        submitted = st.form_submit_button("GÉNÉRER LE PROGRAMME")
        if submitted:
            with st.spinner("Le Cerbère interroge le Graphe Scientifique..."):
                profile = st.session_state.user_profile
                context = {
                    "time": time_avail,
                    "energy": energy,
                    "daily_pain": daily_pain,
                    "note": note,
                }
                
                safe_exos = get_safe_exercises(profile, context)
                if not safe_exos:
                    st.error(
                        "Trop de contraintes (Blessures + Matériel). "
                        "Impossible de trouver des exercices sûrs.\n\n"
                        "➜ Essaie de réduire les zones de douleur ou d'ajouter du matériel."
                    )
                    return
                
                workout_plan = generate_session_with_llm(
                    profile,
                    context,
                    safe_exos,
                    st.session_state.last_feedback,
                )
                if workout_plan is None:
                    st.error("Impossible de générer la séance. Réessaie dans un instant.")
                    return

                st.session_state.workout_plan = workout_plan
                st.session_state.session_time = time_avail
                st.session_state.page = "workout"
                st.rerun()


def render_exercise_card(ex: dict, section_key: str, idx: int):
    """Affiche un exercice sous forme de 'carte' avec vidéo, détails, checkbox."""
    name = ex.get("name", "Exercice")
    sets = ex.get("sets")
    reps = ex.get("reps")
    duration_min = ex.get("duration_min")
    video = ex.get("video")
    instruction = ex.get("instruction", "")

    details = []
    if duration_min:
        details.append(f"{duration_min} min")
    if sets:
        details.append(f"{sets} série(s)")
    if reps:
        details.append(f"{reps} reps")

    detail_line = " • ".join(details) if details else "Durée / volume libre"

    with st.expander(f"{name} — {detail_line}", expanded=False):
        if video:
            # Si c'est une URL de recherche YouTube -> on affiche un bouton
            if "youtube.com/results?search_query=" in video:
                st.markdown(
                    f"[🔎 Voir les tutos pour cet exercice sur YouTube]({video})",
                    unsafe_allow_html=False,
                )
            else:
                # Sinon on tente de l'embarquer comme vraie vidéo
                st.video(video)

        st.markdown(f"**Consigne :** {instruction}")
        st.checkbox("Fait ✅", key=f"done_{section_key}_{idx}")


def page_workout():
    st.title("🏋️‍♂️ Ta Séance personnalisée")

    plan = st.session_state.workout_plan

    if plan is None:
        st.warning("Aucune séance en cours. Retour à l'accueil.")
        if st.button("Retour au QG"):
            st.session_state.page = "home"
            st.rerun()
        return

    # ========== CHRONO EN HAUT ==========
    # Sécurité au cas où les variables n'existent pas encore
    if "timer_running" not in st.session_state:
        st.session_state.timer_running = False
    if "timer_remaining" not in st.session_state:
        st.session_state.timer_remaining = 0

    st.markdown("---")
    st.subheader("⏱ Chrono global (optionnel)")

    # Initialisation de la durée si rien n'est lancé
    if st.session_state.timer_remaining <= 0 and not st.session_state.timer_running:
        st.session_state.timer_remaining = 0

    # Affichage du temps restant
    if st.session_state.timer_remaining > 0 or st.session_state.timer_running:
        m, s = divmod(max(st.session_state.timer_remaining, 0), 60)
        st.metric("Temps restant (approx.)", f"{m:02d}:{s:02d}")
    else:
        st.write("Aucun chrono en cours.")

    # Boutons de contrôle du chrono et de la séance
    col1, col2 = st.columns(2)

    with col1:
        if not st.session_state.timer_running:
            # Lancer ou reprendre le chrono
            if st.button("Lancer / Reprendre le chrono", use_container_width=True):
                if st.session_state.timer_remaining <= 0:
                    # Premier lancement : on initialise à la durée de la séance
                    st.session_state.timer_remaining = st.session_state.session_time * 60
                st.session_state.timer_running = True
                st.rerun()
        else:
            # Mettre en pause le chrono
            if st.button("Mettre en pause le chrono", use_container_width=True):
                st.session_state.timer_running = False
                st.rerun()

    with col2:
        # Arrêter la séance à tout moment
        if st.button("Arrêter la séance maintenant", use_container_width=True):
            st.session_state.timer_running = False
            st.session_state.timer_remaining = 0
            st.session_state.page = "feedback"
            st.rerun()

    # Logique de décrémentation du chrono (tick de 1 seconde)
    if st.session_state.timer_running and st.session_state.timer_remaining > 0:
        time.sleep(1)
        st.session_state.timer_remaining -= 1

        if st.session_state.timer_remaining <= 0:
            st.session_state.timer_running = False
            st.session_state.timer_remaining = 0
            st.balloons()
            st.success("Séance terminée ! Tu peux arrêter la séance quand tu veux.")
        else:
            st.rerun()

    st.markdown("---")
    # ========== AFFICHAGE DE LA SEANCE EN DESSOUS ==========

    # Si pour une raison quelconque ce n'est pas un dict JSON, fallback en markdown
    if not isinstance(plan, dict):
        st.markdown(plan)
    else:
        strategie = plan.get("strategie", [])
        seance = plan.get("seance", {})
        echauffement = seance.get("echauffement", [])
        corps = seance.get("corps", [])
        retour_calme = seance.get("retour_calme", [])
        mot_fin = plan.get("mot_fin", "")

        # Stratégie
        if strategie:
            st.subheader("🎯 Stratégie du coach")
            for bullet in strategie:
                st.markdown(f"- {bullet}")

        # Échauffement
        if echauffement:
            st.subheader("🔥 Échauffement")
            for idx, ex in enumerate(echauffement):
                render_exercise_card(ex, "echauffement", idx)

        # Corps de séance
        if corps:
            st.subheader("💪 Corps de séance")
            for idx, ex in enumerate(corps):
                render_exercise_card(ex, "corps", idx)

        # Retour au calme
        if retour_calme:
            st.subheader("🧘 Retour au calme")
            for idx, ex in enumerate(retour_calme):
                render_exercise_card(ex, "retour_calme", idx)

        if mot_fin:
            st.markdown("---")
            st.info(f"🗣️ Mot du coach : {mot_fin}")

    # Bouton “J'ai fini” (optionnel si l’utilisateur ne veut pas utiliser le chrono)
    if st.button("J'AI FINI ✅", type="primary", use_container_width=True):
        st.session_state.timer_running = False
        st.session_state.timer_remaining = 0
        st.session_state.page = "feedback"
        st.rerun()


def page_feedback():
    st.title("Debriefing 📝")
    st.caption("Tes retours servent à entraîner ton coach IA pour les prochaines séances.")

    with st.form("feed"):
        st.write("Comment as-tu trouvé la séance ?")
        feel = st.select_slider(
            "",
            options=["Trop facile", "Facile", "Parfait", "Dur", "Trop dur"],
            value="Parfait",
        )
        
        c1, c2 = st.columns(2)
        with c1:
            clear_instr = st.checkbox("Instructions claires ?")
        with c2:
            good_fit = st.checkbox("Adapté à mon besoin ?")
        
        msg = st.text_input("Un détail à ajuster pour la prochaine fois ?")

        submitted = st.form_submit_button("Envoyer")
        if submitted:
            st.session_state.last_feedback = {
                "ressenti": feel,
                "instructions_claires": clear_instr,
                "adapte_besoin": good_fit,
                "message": msg,
            }
            st.session_state.sessions_done = st.session_state.get("sessions_done", 0) + 1
            st.success("💾 Feedback enregistré ! Ton coach adaptera la prochaine séance.")
            time.sleep(2)
            st.session_state.page = "home"
            st.rerun()

# ========================= 6. ROUTING =========================

if st.session_state.page == "onboarding":
    page_onboarding()
elif st.session_state.page == "home":
    page_home()
elif st.session_state.page == "checkin":
    page_checkin()
elif st.session_state.page == "workout":
    page_workout()
elif st.session_state.page == "feedback":
    page_feedback()