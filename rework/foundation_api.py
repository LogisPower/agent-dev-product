"""Optional registration in the existing authenticated Logis candidate API."""

def register(app, foundation, scope, allowed):
    from fastapi import Depends, HTTPException, Request
    def check(project, permissions, write=False):
        allowed(project, permissions)
        if write and not permissions.get('write'):
            raise HTTPException(403, 'Read-only credentials')

    @app.get('/api/projects/{project}/foundation')
    def query(project: str, request: Request, permissions=Depends(scope)):
        check(project, permissions)
        args = dict(request.query_params)
        action = args.pop('action', 'status')
        try:
            return foundation.query(project, action, **args)
        except KeyError as error:
            raise HTTPException(404, str(error)) from error
        except (ValueError, OSError) as error:
            raise HTTPException(409, str(error)) from error

    @app.post('/api/projects/{project}/foundation/{action}')
    def command(project: str, action: str, body: dict, permissions=Depends(scope)):
        check(project, permissions, write=True)
        try:
            return foundation.command(project, action, body,principal=permissions.get('_dispatch_identity'))
        except KeyError as error:
            raise HTTPException(404, str(error)) from error
        except (ValueError, OSError) as error:
            raise HTTPException(409, str(error)) from error

    app.state.foundation = foundation
