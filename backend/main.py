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
            # Définition des agents (SANS LE ROUTEUR)
            
            self.stylist = Agent(
                role='Styliste CSS Expert',
                goal='Générer du code CSS valide basé sur des instructions pour modifier le style visuel de l\'interface. La réponse DOIT être UNIQUEMENT un objet JSON valide.',
                backstory='Designer UI/UX expert en CSS, spécialisé dans la traduction de demandes en code CSS précis et valide, retourné exclusivement en format JSON. Exemple de sortie : {"body": {"background-color": "red"}}',
                llm=llm_config, # Assurez-vous que get_llm_config() est défini et fonctionnel
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
                agents=[self.researcher, self.analyst, self.writer], # Le styliste est utilisé séparément
                tasks=[], 
                verbose=True,
                process=Process.sequential # Traitement séquentiel pour le workflow de recherche
            )
            logger.info("Agents CrewAI (sans routeur) initialisés avec succès")
        except Exception as e:
            logger.error(f"Erreur d'initialisation des agents CrewAI: {e}", exc_info=True)
            raise

    async def process_message(self, message: str) -> str:
        try:
            logger.info(f"Traitement du message: {message[:70]}...")
            task_type = ""

            # Routage simplifié par heuristique sur des mots-clés
            style_keywords = ['couleur', 'color', 'style', 'fond', 'arrière-plan', 'background', 'css', 'modifier l\'apparence', 'changer le look']
            if any(keyword in message.lower() for keyword in style_keywords):
                task_type = "style"
            else:
                task_type = "recherche"

            if task_type == "style":
                logger.info("Déclenchement du workflow de style")
                
                style_task = Task(
                    description=f"Génère les modifications CSS pour la demande utilisateur : '{message}'. "
                                "La réponse DOIT être UNIQUEMENT un objet JSON valide contenant les sélecteurs CSS comme clés et un objet de propriétés CSS comme valeurs. "
                                "Par exemple : {\"body\": {\"background-color\": \"red\"}, \"h1\": {\"color\": \"blue\"}}. N'ajoute aucun texte explicatif en dehors du JSON.",
                    agent=self.stylist,
                    expected_output="Un objet JSON valide unique avec les modifications CSS."
                )
                
                style_result_str = await self._run_task(style_task) # _run_task exécute une tâche avec un agent
                
                style_changes_json = {}
                raw_agent_output_for_error_log = style_result_str # Conserver la sortie brute originale pour les logs d'erreur

                try:
                    # Tentative 1: Essayer de parser directement la sortie de l'agent (après un strip simple)
                    # Cela peut fonctionner si l'agent retourne du JSON pur.
                    json_str_attempt1 = style_result_str.strip()
                    logger.info(f"Attempt 1: Direct parse of stripped agent output: >>>{json_str_attempt1}<<<")
                    logger.info(f"repr(json_str_attempt1): {repr(json_str_attempt1)}")
                    style_changes_json = json.loads(json_str_attempt1)
                    logger.info("Attempt 1: Direct parse successful.")

                except json.JSONDecodeError as e1:
                    logger.warning(f"Attempt 1 (direct parse) failed: {e1}. Proceeding to regex extraction.")
                    
                    # Tentative 2: Utiliser l'extraction par regex (votre méthode originale)
                    # Cela est utile si le JSON est enrobé de texte ou de démarqueurs de code.
                    match = re.search(r'(\{[\s\S]*?\})', style_result_str) # Utiliser style_result_str original pour le regex
                    if match:
                        json_str_attempt2_regex = match.group(1)
                        logger.info(f"Attempt 2: Regex extracted json_str: >>>{json_str_attempt2_regex}<<<")
                        logger.info(f"repr(json_str_attempt2_regex): {repr(json_str_attempt2_regex)}")
                        try:
                            style_changes_json = json.loads(json_str_attempt2_regex)
                            logger.info("Attempt 2: Regex extraction and parse successful.")
                        except json.JSONDecodeError as e2:
                            logger.error(f"Attempt 2 (regex parse) failed: {e2}. Original agent output: >>>{raw_agent_output_for_error_log}<<<", exc_info=True)
                            return json.dumps({"type": "error", "message": f"Format de réponse incorrect du styliste (après regex). Réponse brute: {raw_agent_output_for_error_log}"})
                    else:
                        logger.warning(f"Attempt 2 (regex search): No JSON object found. Original agent output: >>>{raw_agent_output_for_error_log}<<<")
                        return json.dumps({"type": "error", "message": "Le styliste n'a pas retourné de format JSON détectable."})
                
                # Si nous arrivons ici, une des tentatives de parsing a réussi.
                return json.dumps({
                    "type": "style",
                    "message": "Modifications de style CSS générées.",
                    "style_changes": style_changes_json
                })

            elif task_type == "recherche":
                logger.info("Déclenchement du workflow de recherche")
                research_task = Task(
                    description=f"Effectue une recherche approfondie et détaillée sur la requête suivante : '{message}'.",
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
                final_research_result = await self._run_crew() # _run_crew exécute self.crew.kickoff()
                
                return json.dumps({"type": "recherche", "message": final_research_result})
            
            else: # Ne devrait pas être atteint avec la logique actuelle
                logger.error(f"Logique de routage interne a échoué pour le message: {message}")
                return json.dumps({"type": "error", "message": "Erreur interne de routage de la tâche."})

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