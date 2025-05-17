from fastapi.responses import JSONResponse

def standard_response(data=None, message="Success", detail=None, status_code=200):
    return JSONResponse(
        status_code=status_code,
        content={
            "message": message,
            "detail": detail,
            "data": data
        }
    )
