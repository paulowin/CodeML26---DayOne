"""Vocabulaire connu du carnet : sert à reconnaître (et corriger) le texte libre lu par l'OCR.

Une valeur hors de ce vocabulaire n'est pas fausse, mais elle n'est pas vérifiable : en mode OCR,
elle ne devient CONNU que si le 2e avis lit exactement la même chose (sinon : à vérifier).
"""

# Provinces et préfectures du Maroc (forme officielle, variantes)
PROVINCES_MAROC = tuple((p, ()) for p in (
    "Agadir-Ida-Ou-Tanane", "Al Haouz", "Al Hoceïma", "Aousserd", "Assa-Zag", "Azilal", "Béni Mellal",
    "Benslimane", "Berkane", "Berrechid", "Boujdour", "Boulemane", "Casablanca", "Chefchaouen",
    "Chichaoua", "Chtouka-Aït Baha", "Driouch", "El Hajeb", "El Jadida", "El Kelâa des Sraghna",
    "Errachidia", "Es-Semara", "Essaouira", "Fahs-Anjra", "Fès", "Figuig", "Fquih Ben Salah", "Guelmim",
    "Guercif", "Ifrane", "Inezgane-Aït Melloul", "Jerada", "Kénitra", "Khémisset", "Khénifra", "Khouribga",
    "Laâyoune", "Larache", "M'diq-Fnideq", "Marrakech", "Médiouna", "Meknès", "Midelt", "Mohammédia",
    "Moulay Yacoub", "Nador", "Nouaceur", "Ouarzazate", "Oued Ed-Dahab", "Ouezzane", "Oujda-Angad",
    "Rabat", "Rehamna", "Safi", "Salé", "Sefrou", "Settat", "Sidi Bennour", "Sidi Ifni", "Sidi Kacem",
    "Sidi Slimane", "Skhirate-Témara", "Tan-Tan", "Tanger-Assilah", "Taounate", "Taourirt", "Tarfaya",
    "Taroudant", "Tata", "Taza", "Tétouan", "Tinghir", "Tiznit", "Youssoufia", "Zagora",
))

PROFESSIONS = (
    "Femme au foyer", "Sans profession", "Agricultrice", "Agriculteur", "Étudiante", "Étudiant", "Élève",
    "Couturière", "Commerçante", "Commerçant", "Employée", "Employé", "Fonctionnaire", "Ouvrière", "Ouvrier",
    "Chauffeur", "Mécanicien", "Maçon", "Enseignante", "Enseignant", "Infirmière", "Infirmier",
    "Journalier", "Artisan", "Artisane", "Cultivateur", "Éleveur", "Pêcheur", "Menuisier", "Électricien",
    "Plombier", "Coiffeuse", "Vendeuse", "Vendeur", "Militaire", "Policier", "Retraité", "Chômeur",
)

NIVEAUX = ("Aucun", "Analphabète", "Primaire", "Collège", "Lycée", "Supérieur", "Universitaire")

TERMES_CARNET = (
    "RAS", "Normaux", "Normales", "Normal", "Normale", "Oui", "Non", "Neg", "Pos", "Négatif", "Positif",
    "Immune", "Non immune", "Fermé", "Ouvert", "Céphalique", "Siège", "Transverse", "Aucun", "Aucune",
    "Néant", "Pâles", "Colorées", "Voie basse", "Césarienne", "Forceps", "Ventouse", "Non fait", "Fait",
    "Propre", "Propre, sèche", "Infectée", "Cycles réguliers", "Cycles irréguliers", "Père", "Mère", "Oncle",
    "Tante", "Frère", "Sœur", "Grand-père", "Grand-mère", "Cousin", "Cousine", "Appendicectomie",
    "Cholécystectomie", "Asthme", "Asthme léger", "HTA", "Diabète", "Épilepsie", "Anémie", "Cardiopathie",
    "Maternité", "Hôpital", "Domicile", "Clinique", "SFA", "Souffrance fœtale", "Utérus cicatriciel",
    "Pré-éclampsie", "Pré-éclampsie sévère", "Éclampsie", "Hémorragie", "Infection", "Dystocie",
    "Poursuivre l'allaitement exclusif", "Allaitement exclusif", "Vit. D 400 UI/j", "Fer 2 cp/j", "Fer",
    "Acide folique", "Souhaite en discuter avec son mari", "Pilule", "DIU", "Préservatif", "Implant",
)

VOCABULAIRE_TEXTE = TERMES_CARNET + PROFESSIONS + NIVEAUX + tuple(p for p, _ in PROVINCES_MAROC)
