# Python venv version: 3.12.8
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List, Dict, Any, Optional
import json
import asyncio
import logging
import os
import re
from crewai import Agent, Task, Crew, Process, LLM
from dotenv import load_dotenv

# Charger les variables d'environnement
load_dotenv()

# Configuration du logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Configuration de l'application FastAPI
app = FastAPI()

# Configuration CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Configuration Mistral
MISTRAL_API_KEY = os.getenv("MISTRAL_API_KEY")
llm_config = LLM (
    model="mistral/mistral-small",
    api_key=MISTRAL_API_KEY,
    temperature=0.7,
    max_tokens=2000
)

# Gestionnaire de connexions WebSocket
class ConnectionManager:
    def __init__(self):
        self.active_connections: List[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)
        logger.info(f"Nouvelle connexion WebSocket. Total: {len(self.active_connections)}")

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)
            logger.info(f"Connexion fermée. Total: {len(self.active_connections)}")

    async def send_personal_message(self, message: str, websocket: WebSocket):
        try:
            await websocket.send_text(message)
        except Exception as e:
            logger.error(f"Erreur d'envoi: {e}")

manager = ConnectionManager()

# Configuration des agents CrewAI
class CrewManager:
    def __init__(self):
        try:
            self.router = Agent(
                role='Agent de Routage Intelligent',
                goal="Analyser la requête de l'utilisateur et déterminer si elle concerne une modification de style CSS ou une recherche d'information. "
                     "Extraire les instructions pertinentes pour l'agent cible.",
                backstory="Expert en compréhension du langage naturel, capable d'identifier l'intention principale d'une requête et de la préparer pour l'agent spécialisé approprié. "
                          "Doit retourner un objet JSON avec les clés 'agent_cible' ('styliste' ou 'chercheur') et 'details_pour_agent' (la requête reformulée ou les instructions spécifiques). "
                          "Exemple pour style: {\"agent_cible\": \"styliste\", \"details_pour_agent\": \"Mettre le fond en rouge et le texte des titres h1 en bleu\"}. "
                          "Exemple pour recherche: {\"agent_cible\": \"chercheur\", \"details_pour_agent\": \"Explique la photosynthèse en détail.\"}",
                llm=llm_config, # Utilise la configuration LLM globale
                verbose=True,
                allow_delegation=False # Le routeur ne délègue pas
            )

            self.stylist = Agent(
                role='Styliste CSS Expert',
                goal='Générer du code CSS valide basé sur des instructions pour modifier le style visuel de l\'interface. La réponse DOIT être UNIQUEMENT un objet JSON valide.',
                backstory='Designer UI/UX expert en CSS, spécialisé dans la traduction de demandes en code CSS précis et valide, retourné exclusivement en format JSON. Exemple de sortie : {"body": {"background-color": "red"}}',
                llm=llm_config, 
                verbose=True,
                allow_delegation=False
            )
            
            self.researcher = Agent(
                role='Chercheur Principal',
                goal='Trouver des informations précises, vérifiées et détaillées sur un sujet donné, en fournissant des sources lorsque pertinent.',
                backstory='Expert en recherche documentaire approfondie, capable de synthétiser des informations complexes issues de sources multiples et fiables.',
                llm=llm_config,
                verbose=True,
                allow_delegation=False 
            )

            self.analyst = Agent(
                role='Analyste de Données Senior',
                goal='Analyser en profondeur les informations et données pour en extraire des insights clés, des tendances et des conclusions pertinentes.',
                backstory='Spécialiste en analyse de données, transformant des informations brutes en interprétations claires et actionnables.',
                llm=llm_config,
                verbose=True,
                allow_delegation=False
            )
            
            self.writer = Agent(
                role='Rédacteur Technique en Chef',
                goal='Produire une réponse finale claire, concise, structurée et bien argumentée, basée sur les informations et analyses fournies.',
                backstory='Rédacteur technique expérimenté, maître dans l\'art de communiquer des informations complexes de manière accessible et engageante.',
                llm=llm_config,
                verbose=True,
                allow_delegation=False
            )

            # Crew principal pour la recherche (sans manager_agent)
            self.crew = Crew(
                agents=[self.researcher, self.analyst, self.writer], 
                tasks=[], 
                verbose=True,
                process=Process.sequential 
            )
            logger.info("Agents CrewAI (avec routeur) initialisés avec succès")
        except Exception as e:
            logger.error(f"Erreur d'initialisation des agents CrewAI: {e}", exc_info=True)
            raise

    async def process_message(self, message: str) -> str:
        try:
            logger.info(f"Traitement du message: {message[:70]}...")

            # 1. Tâche de Routage
            routing_task_description = (
                f"Analyse la requête utilisateur suivante : '{message}'. "
                "Détermine si c'est une demande de style CSS ou une recherche d'information. "
                "Retourne un objet JSON avec les clés 'agent_cible' (valeurs possibles: 'styliste' ou 'chercheur') "
                "et 'details_pour_agent' (contenant la requête originale ou les instructions spécifiques pour l'agent cible). "
                "Assure-toi que 'details_pour_agent' est pertinent pour l'agent désigné. "
                "Par exemple, pour une demande de style, 'details_pour_agent' devrait être les instructions de style. "
                "Pour une recherche, ce serait la question de recherche."
            )
            routing_task = Task(
                description=routing_task_description,
                agent=self.router,
                expected_output="Un objet JSON unique avec les clés 'agent_cible' et 'details_pour_agent'."
            )

            routing_result_str = await self._run_task(routing_task)
            logger.info(f"Sortie brute du routeur: >>>{routing_result_str}<<<")
            logger.info(f"repr(Sortie brute du routeur): {repr(routing_result_str)}")

            route_data = {}
            try:
                # Essayer d'extraire le JSON de la sortie du routeur
                match = re.search(r'(\{[\s\S]*?\})', routing_result_str)
                if match:
                    json_route_str = match.group(1)
                    logger.info(f"JSON extrait du routeur: >>>{json_route_str}<<<")
                    logger.info(f"repr(JSON extrait du routeur): {repr(json_route_str)}")
                    route_data = json.loads(json_route_str)
                else:
                    raise json.JSONDecodeError("Aucun objet JSON trouvé dans la sortie du routeur.", routing_result_str, 0)
            except json.JSONDecodeError as e:
                logger.error(f"Erreur de décodage JSON (routeur): {e}. Sortie brute: {routing_result_str}", exc_info=True)
                # Fallback vers la recherche si le routage échoue
                route_data = {"agent_cible": "chercheur", "details_pour_agent": message}
                logger.warning("Routage échoué, fallback vers agent chercheur.")

            agent_cible = route_data.get("agent_cible", "chercheur").lower()
            details_pour_agent = route_data.get("details_pour_agent", message)

            # 2. Exécution basée sur la décision du Routeur
            if agent_cible == "styliste":
                logger.info(f"Routeur a choisi: Styliste. Détails: {details_pour_agent}")
                
                style_task = Task(
                    description=f"Génère les modifications CSS pour la demande suivante : '{details_pour_agent}'. "
                                "La réponse DOIT être UNIQUEMENT un objet JSON valide contenant les sélecteurs CSS comme clés et un objet de propriétés CSS comme valeurs. "
                                "Par exemple : {\"body\": {\"background-color\": \"red\"}}. N'ajoute aucun texte explicatif en dehors du JSON.",
                    agent=self.stylist,
                    expected_output="Un objet JSON valide unique avec les modifications CSS."
                )
                
                style_result_str = await self._run_task(style_task)
                raw_agent_output_for_error_log = style_result_str # Conserver pour les logs d'erreur
                
                style_changes_json = {}
                try:
                    # Nettoyer la chaîne de sortie de l'agent (enlever les espaces/newlines au début/fin)
                    processed_output = style_result_str.strip()
                    
                    # Trouver la première accolade ouvrante et la dernière accolade fermante
                    first_brace = processed_output.find('{')
                    last_brace = processed_output.rfind('}')
                    
                    if first_brace != -1 and last_brace != -1 and last_brace > first_brace:
                        json_style_str = processed_output[first_brace : last_brace + 1]
                        logger.info(f"JSON extrait par find/rfind: >>>{json_style_str}<<<")
                        logger.info(f"repr(JSON extrait par find/rfind): {repr(json_style_str)}")
                        style_changes_json = json.loads(json_style_str)
                    else:
                        # Si la méthode find/rfind ne trouve pas un JSON plausible, lever une erreur
                        logger.error(f"Impossible d'extraire un bloc JSON valide de la sortie du styliste avec find/rfind. Sortie brute: {raw_agent_output_for_error_log}")
                        raise json.JSONDecodeError("Aucun bloc JSON valide extractible de la sortie du styliste.", style_result_str, 0)
                        
                except json.JSONDecodeError as e:
                    logger.error(f"Erreur de décodage JSON (styliste): {e}. Sortie brute: {raw_agent_output_for_error_log}", exc_info=True)
                    return json.dumps({"type": "error", "message": f"Format de réponse incorrect du styliste. Réponse: {raw_agent_output_for_error_log}"})

                return json.dumps({
                    "type": "style",
                    "message": "Modifications de style CSS générées.",
                    "style_changes": style_changes_json
                })

            elif agent_cible == "chercheur":
                logger.info(f"Routeur a choisi: Chercheur. Détails: {details_pour_agent}")
                research_task = Task(
                    description=f"Effectue une recherche approfondie et détaillée sur la requête suivante : '{details_pour_agent}'.",
                    agent=self.researcher,
                    expected_output="Un rapport de recherche complet, factuel et bien structuré."
                )
                analysis_task = Task(
                    description="Analyse les informations du rapport de recherche pour en extraire les points essentiels, les tendances et les conclusions pertinentes.",
                    agent=self.analyst,
                    expected_output="Une synthèse analytique claire avec les principaux insights.",
                    context=[research_task]
                )
                writing_task = Task(
                    description="Rédige une réponse finale informative, claire et bien organisée, basée sur l'analyse fournie.",
                    agent=self.writer,
                    expected_output="Une réponse utilisateur finale, bien rédigée et complète.",
                    context=[analysis_task]
                )
                
                self.crew.tasks = [research_task, analysis_task, writing_task]
                final_research_result = await self._run_crew()
                
                return json.dumps({"type": "recherche", "message": final_research_result})
            
            else:
                logger.error(f"Agent cible inconnu '{agent_cible}' retourné par le routeur.")
                return json.dumps({"type": "error", "message": f"Erreur interne: agent cible inconnu '{agent_cible}'."})

        except Exception as e:
            logger.error(f"Erreur globale dans process_message: {e}", exc_info=True)
            return json.dumps({"type": "error", "message": f"Une erreur serveur inattendue est survenue: {str(e)}"})

    # Méthodes auxiliaires pour exécution asynchrone
    async def _run_task(self, task: Task) -> str:
        # Créer un équipage temporaire avec uniquement cette tâche
        temp_crew = Crew(
            agents=[task.agent],
            tasks=[task],
            verbose=True
        )
    
        # Exécuter l'équipage temporaire de manière non-bloquante
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(None, temp_crew.kickoff)
    
        # Extraire le texte du résultat (CrewOutput)
        if hasattr(result, 'final_output'):
            return result.final_output
        elif hasattr(result, 'raw_output'):
            return result.raw_output
        else:
            return str(result)  # Fallback pour les autres cas
    
    async def _run_crew(self) -> str:
        # Cette méthode exécute le crew complet de manière non-bloquante
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(None, self.crew.kickoff)
    
        # Extraire le texte du résultat (CrewOutput)
        if hasattr(result, 'final_output'):
            return result.final_output
        elif hasattr(result, 'raw_output'):
            return result.raw_output
        else:
            return str(result)  # Fallback pour les autres cas

# Initialisation
crew_manager = CrewManager()

# Modèle Pydantic pour les messages
class UserMessage(BaseModel):
    message: str

# Endpoint WebSocket
@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        while True:
            data = await websocket.receive_text()
            message_data = json.loads(data)
            user_message = message_data.get("message", "")
            
            await manager.send_personal_message(
                json.dumps({"sender": "system", "status": "processing"}),
                websocket
            )
            
            response = await crew_manager.process_message(user_message)
            
            # Analyser si la réponse est une modification de style ou une réponse textuelle
            try:
                response_data = json.loads(response)
                
                if response_data.get("type") == "style":
                    # Envoyer les modifications de style
                    await manager.send_personal_message(
                        json.dumps({
                            "sender": "crew", 
                            "type": "style",
                            "message": response_data.get("message", ""),
                            "style_changes": response_data.get("style_changes", {})
                        }),
                        websocket
                    )
                else:
                    # Envoyer la réponse textuelle
                    await manager.send_personal_message(
                        json.dumps({
                            "sender": "crew", 
                            "type": "message",
                            "message": response_data.get("message", "")
                        }),
                        websocket
                    )
            except json.JSONDecodeError:
                # Fallback si la réponse n'est pas en JSON
                await manager.send_personal_message(
                    json.dumps({"sender": "crew", "type": "message", "message": response}),
                    websocket
                )

    except WebSocketDisconnect:
        manager.disconnect(websocket)
    except Exception as e:
        logger.error(f"Erreur WebSocket: {str(e)}")

# Endpoint santé
@app.get("/health")
def health_check():
    return {"status": "actif", "service": "Système Multi-Agents"}

# Point d'entrée
if __name__ == "__main__":
    import uvicorn
    logger.info("Démarrage du serveur...")
    uvicorn.run(app, host="0.0.0.0", port=8000)