from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from typing import List, Dict, Any, Optional
import json
import asyncio
import logging
import threading
from crewai import Agent, Task, Crew, Process
from dotenv import load_dotenv
load_dotenv()

# Configure logging
logging.basicConfig(level=logging.INFO, 
                    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# FastAPI app setup
app = FastAPI()

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # In production, specify exact domains
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# WebSocket connection manager
class ConnectionManager:
    def __init__(self):
        self.active_connections: List[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)
        logger.info(f"New WebSocket connection. Active connections: {len(self.active_connections)}")

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)
            logger.info(f"WebSocket disconnected. Active connections: {len(self.active_connections)}")

    async def send_personal_message(self, message: str, websocket: WebSocket):
        try:
            await websocket.send_text(message)
        except Exception as e:
            logger.error(f"Error sending message: {e}")
            raise

    async def broadcast(self, message: str):
        for connection in self.active_connections:
            try:
                await connection.send_text(message)
            except Exception as e:
                logger.error(f"Error broadcasting message: {e}")
                # Continue with other connections even if one fails

manager = ConnectionManager()

# CrewAI Agents setup
class CrewManager:
    def __init__(self):
        try:
            # Configuration de l'API OpenAI (remplacez par votre clé API)
            api_key = "votre_clé_api_openai_ici"
            
            # Définition des agents avec des rôles spécifiques et la clé API
            self.researcher = Agent(
                role='Researcher',
                goal='Find and provide accurate information',
                backstory='You are an expert researcher who quickly finds relevant information.',
                allow_delegation=True,
                verbose=True,
                llm_config={"api_key": api_key, "model": "gpt-4o-mini"}  # Configuration de l'API
            )
            
            self.analyst = Agent(
                role='Analyst',
                goal='Analyze information and extract insights',
                backstory='You analyze data and information to extract meaningful insights.',
                allow_delegation=True,
                verbose=True,
                llm_config={"api_key": api_key, "model": "gpt-4o-mini"}
            )
            
            self.writer = Agent(
                role='Writer',
                goal='Communicate insights clearly and effectively',
                backstory='You are skilled at presenting information in a clear, accessible manner.',
                allow_delegation=True,
                verbose=True,
                llm_config={"api_key": api_key, "model": "gpt-4o-mini"}
            )
            
            # Création de l'équipe
            self.crew = Crew(
                agents=[self.researcher, self.analyst, self.writer],
                tasks=[],
                verbose=True,
                process=Process.sequential
            )
            logger.info("CrewAI agents initialized successfully")
        except Exception as e:
            logger.error(f"Error initializing CrewAI: {e}")
            raise
    
    async def process_message(self, message: str) -> str:
        try:
            logger.info(f"Processing message: {message[:50]}...")

            # Création des tâches basées sur le message utilisateur
            research_task = Task(
                description=f"Research information related to: {message}",
                agent=self.researcher,
                expected_output="Comprehensive research findings on the given topic"
            )

            analysis_task = Task(
                description="Analyze the research findings and identify key insights",
                agent=self.analyst,
                expected_output="Analysis report with key insights from research"
            )

            writing_task = Task(
                description="Create a clear response based on the analysis",
                agent=self.writer,
                expected_output="Final response for the user based on analysis"
            )

            # Mise à jour des tâches de l'équipe
            self.crew.tasks = [research_task, analysis_task, writing_task]

            # Exécution du processus de l'équipe
            # Pour une implémentation réelle, utilisez:
            result = self.crew.kickoff()

            # Retourne le résultat
            logger.info("Message processing completed")
            return result
        except Exception as e:
            logger.error(f"Error in process_message: {e}")
            return f"Sorry, an error occurred while processing your message: {str(e)}"

# Initialize the crew manager
try:
    crew_manager = CrewManager()
except Exception as e:
    logger.error(f"Failed to initialize CrewManager: {e}")
    # We'll continue to allow the app to start, but we'll handle errors when processing messages

# Message processing class
class UserMessage(BaseModel):
    message: str

# Health check response
class HealthResponse(BaseModel):
    status: str
    service: str
    connections: int

# WebSocket endpoint for chat
@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        # Send initial connection confirmation
        await manager.send_personal_message(
            json.dumps({
                "sender": "system",
                "type": "connection",
                "status": "connected",
                "message": "Successfully connected to the server"
            }),
            websocket
        )
        
        while True:
            # Receive and parse message
            try:
                data = await websocket.receive_text()
                logger.info(f"Received WebSocket message: {data[:50]}...")
                
                # Parse the received message
                message_data = json.loads(data)
                user_message = message_data.get("message", "")
                
                if not user_message:
                    await manager.send_personal_message(
                        json.dumps({
                            "sender": "system",
                            "type": "error",
                            "message": "Empty message received"
                        }),
                        websocket
                    )
                    continue
                
                # Send acknowledgement that message was received
                await manager.send_personal_message(
                    json.dumps({
                        "sender": "system",
                        "type": "ack",
                        "message": "Message received, processing..."
                    }),
                    websocket
                )
                
                # Process the message through CrewAI
                response = await crew_manager.process_message(user_message)
                
                # Send response to the client
                await manager.send_personal_message(
                    json.dumps({
                        "sender": "crew",
                        "type": "response",
                        "message": response
                    }),
                    websocket
                )
                
            except json.JSONDecodeError:
                logger.error("Invalid JSON received")
                await manager.send_personal_message(
                    json.dumps({
                        "sender": "system",
                        "type": "error",
                        "message": "Invalid message format"
                    }),
                    websocket
                )
            except Exception as e:
                logger.error(f"Error processing message: {e}")
                await manager.send_personal_message(
                    json.dumps({
                        "sender": "system",
                        "type": "error",
                        "message": f"Error processing message: {str(e)}"
                    }),
                    websocket
                )
                
    except WebSocketDisconnect:
        logger.info("WebSocket disconnected")
        manager.disconnect(websocket)
    except Exception as e:
        logger.error(f"Unexpected WebSocket error: {e}")
        manager.disconnect(websocket)

# Simple health check endpoint
@app.get("/", response_model=HealthResponse)
def read_root():
    return {
        "status": "online", 
        "service": "Multi-Agent Chat System",
        "connections": len(manager.active_connections)
    }

# Standard REST endpoint to send a message (alternative to WebSocket)
@app.post("/message")
async def process_message(message: UserMessage):
    try:
        response = await crew_manager.process_message(message.message)
        return {"sender": "crew", "message": response}
    except Exception as e:
        logger.error(f"Error in /message endpoint: {e}")
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    import uvicorn
    
    # Log startup message
    logger.info("Starting Multi-Agent Chat System server")
    
    # Start the server
    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="info")