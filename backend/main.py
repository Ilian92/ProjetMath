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

            # Configuration de l'équipe
            self.crew = Crew(
                agents=[self.researcher, self.analyst, self.writer],
                tasks=[],
                verbose=True,
                process=Process.sequential
            )
            logger.info("Agents CrewAI initialisés avec succès")

        except Exception as e:
            logger.error(f"Erreur d'initialisation: {str(e)}")
            raise

    async def process_message(self, message: str) -> str:
        try:
            logger.info(f"Traitement du message: {message[:50]}...")

            # Création des tâches
            research_task = Task(
                description=f"Recherche sur : {message}",
                agent=self.researcher,
                expected_output="Rapport détaillé avec sources fiables"
            )

            analysis_task = Task(
                description="Analyse des données recueillies",
                agent=self.analyst,
                expected_output="Liste d'insights clés et conclusions",
                context=[research_task]
            )

            writing_task = Task(
                description="Rédaction de la réponse finale",
                agent=self.writer,
                expected_output="Réponse structurée en français",
                context=[research_task, analysis_task]
            )

            self.crew.tasks = [research_task, analysis_task, writing_task]
            result = self.crew.kickoff()
            
            return f"Réponse finale :\n\n{result}"

        except Exception as e:
            logger.error(f"Erreur de traitement: {str(e)}")
            return f"Erreur : {str(e)}"

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
            
            await manager.send_personal_message(
                json.dumps({"sender": "crew", "message": response}),
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