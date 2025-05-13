from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List, Dict, Any, Optional
import json
import asyncio
import logging
import os
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
            # Définition des agents
            self.router = Agent(
                role='Routeur',
                goal='Analyser la requête et déterminer quel agent doit intervenir',
                backstory='Expert en compréhension des requêtes utilisateur et en prise de décision',
                llm=llm_config,
                verbose=True,
                allow_delegation=True
            )
            
            self.stylist = Agent(
                role='Styliste',
                goal='Modifier le style visuel de l\'interface',
                backstory='Designer UI/UX spécialisé dans la personnalisation d\'interfaces',
                llm=llm_config,
                verbose=True,
                allow_delegation=False
            )
            
            self.researcher = Agent(
                role='Chercheur',
                goal='Trouver des informations précises et vérifiées',
                backstory='Expert en recherche avec accès aux bases de données scientifiques',
                llm=llm_config,
                verbose=True,
                allow_delegation=False
            )

            self.analyst = Agent(
                role='Analyste',
                goal='Analyser les données et identifier les insights clés',
                backstory='Spécialiste en analyse de données complexes',
                llm=llm_config,
                verbose=True,
                allow_delegation=False
            )

            self.writer = Agent(
                role='Rédacteur',
                goal='Produire une réponse claire et structurée',
                backstory='Rédacteur technique expérimenté',
                llm=llm_config,
                verbose=True,
                allow_delegation=False
            )

            # Configuration de l'équipe avec Process.graph au lieu de sequential
            self.crew = Crew(
                agents=[self.stylist, self.researcher, self.analyst, self.writer],
                tasks=[],
                verbose=True,
                process=Process.hierarchical,
                manager_agent=self.router
            )
            logger.info("Agents CrewAI initialisés avec succès")

        except Exception as e:
            logger.error(f"Erreur d'initialisation: {str(e)}")
            raise

    async def process_message(self, message: str) -> str:
        try:
            logger.info(f"Traitement du message: {message[:50]}...")
            # Étape de routage pour déterminer le workflow
            routing_task = Task(
                description=f"Analyze cette requête utilisateur et détermine quel type de traitement est nécessaire: '{message}'. "
                            f"Si c'est une demande de recherche d'information, réponds avec le JSON: "
                            f"{{\"type\":\"recherche\",\"query\":\"<la requête>\"}}"
                            f"Si c'est une demande de modification de style, réponds avec le JSON: "
                            f"{{\"type\":\"style\",\"instructions\":\"<détails des changements>\",\"elements\":\"<éléments à modifier>\"}}",
                agent=self.router,
                expected_output="JSON avec le type de requête et les détails pertinents"
            )
            # Exécuter la tâche de routage
            routing_result = await self._run_task(routing_task)
            try:
                # Parser la réponse JSON du routeur
                route_data = json.loads(routing_result)
                task_type = route_data.get("type", "").lower()
                if task_type == "style":
                    # Workflow pour les modifications de style
                    style_task = Task(
                        description=f"Génère les modifications CSS pour: {route_data.get('instructions')}. "
                                   f"Éléments à modifier: {route_data.get('elements')}",
                        agent=self.stylist,
                        expected_output="JSON avec les propriétés CSS à modifier et leurs valeurs"
                    )
                    result = await self._run_task(style_task)
                    return json.dumps({
                        "type": "style",
                        "message": f"Modifications de style générées",
                        "style_changes": json.loads(result) if isinstance(result, str) else result
                    })
                else:  # Par défaut, workflow de recherche
                    # Création des tâches pour le chemin de recherche
                    research_task = Task(
                        description=f"Recherche sur : {message}",
                        agent=self.researcher,
                        expected_output="Rapport détaillé avec sources fiables"
                    )
                    analysis_task = Task(
                        description="Analyse des données recueillies",
                        agent=self.analyst,
                        expected_output="Liste d'insights clés et conclusions",
                        context=[research_task]  # Dépend des résultats de recherche
                    )
                    writing_task = Task(
                        description="Rédaction de la réponse finale",
                        agent=self.writer,
                        expected_output="Réponse structurée en français",
                        context=[analysis_task]  # Dépend de l'analyse
                    )
                    # Configuration des tâches et exécution
                    self.crew.tasks = [research_task, analysis_task, writing_task]
                    result = await self._run_crew()
                    return json.dumps({
                        "type": "recherche", 
                        "message": result
                    })
            except json.JSONDecodeError:
                # En cas d'erreur dans le parsing JSON, utiliser le flux de travail de recherche par défaut
                logger.warning(f"Format de réponse du routeur incorrect: {routing_result}")
                # Workflow de secours
                research_task = Task(
                    description=f"Recherche sur : {message}",
                    agent=self.researcher,
                    expected_output="Rapport détaillé"
                )
                self.crew.tasks = [research_task]
                result = await self._run_crew()
                return f"Réponse finale (mode secours) :\n\n{result}"
        except Exception as e:
            logger.error(f"Erreur de traitement: {str(e)}")
            return f"Erreur : {str(e)}"

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