class WSError(Exception):
    '''Root for wspy package exceptions'''
    pass

class WSTypeError(TypeError):
    '''Different type error for WS'''
    pass

class NetworkError(WSError, IOError):
    '''Socket network error occured'''
    pass

class UnmaskError(WSError):
    '''Unmask the frame data occured error'''
    pass