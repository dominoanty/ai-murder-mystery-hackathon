
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from invoke_types import InvocationRequest, InvocationResponse
# from db import pool
import json
from settings import MODEL, MODEL_KEY
from ai import respond_initial, critique, refine, check_whether_to_refine
from datetime import datetime, timezone
import time

# app = FastAPI()
# origins = ["*"]

# app.add_middleware(
#     CORSMiddleware,
#     allow_origins=origins,
#     allow_credentials=True,
#     allow_methods=["*"],
#     allow_headers=["*"],
# )

from flask import Flask, request, jsonify

app = Flask(__name__)

def create_conversation_turn(conn, request: InvocationRequest) -> int:
    with conn.cursor() as cur:        
        serialized_chat_messages = [msg.model_dump() for msg in request.actor.messages]
        cur.execute(
            "INSERT INTO conversation_turns (session_id, character_file_version, model, model_key, actor_name, chat_messages) "
            "VALUES (%s, %s, %s, %s, %s, %s) RETURNING id",
            (request.session_id, request.character_file_version,
             MODEL, MODEL_KEY, request.actor.name, json.dumps(serialized_chat_messages), )
        )
        turn_id = cur.fetchone()[0]

    return turn_id


def store_response(conn, turn_id: int, response: InvocationResponse):
    with conn.cursor() as cur:
        cur.execute(
           "UPDATE conversation_turns SET original_response = %s, critique_response = %s, problems_detected = %s, "
           "final_response = %s, refined_response = %s, finished_at= %s WHERE id=%s",
              (response.original_response, response.critique_response, response.problems_detected, response.final_response,
                response.refined_response, datetime.now(tz=timezone.utc).isoformat(), turn_id, )
        )



def prompt_ai(conn, request: InvocationRequest) -> InvocationResponse:
    turn_id = create_conversation_turn(conn, request)
    print(f"Serving turn {turn_id}")

    # UNREFINED
    unrefined_response = respond_initial(conn, turn_id, request)

    print(f"\nunrefined_response: {unrefined_response}\n")

    critique_response = critique(conn, turn_id, request, unrefined_response)

    print(f"\ncritique_response: {critique_response}\n")

    problems_found = check_whether_to_refine(critique_response)

    if problems_found:
        refined_response = refine(conn, turn_id, request, critique_response, unrefined_response)
        
        final_response = refined_response
    else:
        final_response = unrefined_response
        refined_response = None

    response = InvocationResponse(
        original_response=unrefined_response,
        critique_response=critique_response,
        problems_detected=problems_found,
        final_response=final_response,
        refined_response=refined_response,
    )

    store_start = time.time()
    store_response(conn, turn_id, response)
    print(f"Stored in {time.time() - store_start:.2f}s")

    return response


@app.route("/", methods = ["GET"])
def read_root():
    return {"Hello": "World"}

app = Flask(__name__)

@app.route('/invoke', methods=['POST'])
def post_endpoint():
    print("Hello")
    data = request.json  # Get JSON data from request body
    response = prompt_ai(None, data)
    return jsonify(response), 200  # Return JSON response with status code 200

if __name__ == '__main__':
    app.run(debug=True, port=10000)  # Run the app in debug mode

@app.post("/invoke")
def invoke(request: InvocationRequest):
    print("Received request", flush=True)
    conn = None
    response = prompt_ai(conn, request)

    return response.model_dump()