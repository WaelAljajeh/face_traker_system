import logging

from services.api_server import AttendanceAPIServer

from core.detector import FaceDetector
from core.recognizer import FaceRecognizer
from core.tracker import ByteTrack

from services.database_service import DatabaseService
from services.vector_database import FAISSVectorDB
from core.embedder import FaceEmbedder

from models.database import init_database   # IMPORTANT (you were missing this)

logging.basicConfig(level=logging.INFO)


def main():

    config = {
        "api": {
            "host": "0.0.0.0",
            "port": 8000
        }
    }

    # ===================== INIT DATABASE ENGINE =====================
    engine, SessionLocal = init_database("face_attendance.db")

    # ===================== AI =====================
    # Initialize embedder with InsightFace model
    embedder = FaceEmbedder(
    model_name='buffalo_l',
    det_size=(640, 640),
    det_thresh=0.5,
)  # Auto-loads InsightFace
    
    detector = FaceDetector()
    db_service = DatabaseService(SessionLocal)

    vector_db = FAISSVectorDB(
        embedding_dim=512
    )

    recognizer = FaceRecognizer(
        db_service=db_service,
        vector_db=vector_db,
        normalize=True
    )

    tracker = ByteTrack()

    # ===================== SERVICES =====================
   
    # ===================== SERVER =====================
    server = AttendanceAPIServer(
        config=config,
        detector=detector,
        recognizer=recognizer,
        tracker=tracker,
        db_service=db_service,
        vector_db=vector_db,
        embedders=embedder
    )

    print("🚀 Server running at http://localhost:8000")
    print("📋 API Documentation: http://localhost:8000/docs")

    server.run(
        host=config["api"]["host"],
        port=config["api"]["port"]
    )


if __name__ == "__main__":
    main()