"""Bounded token buffering, preserving multi-byte UTF-8 token sequences."""


class RollingTextDecoder:
    def __init__(self,tokenizer,chunk_tokens=128):
        self.tokenizer=tokenizer
        self.chunk_tokens=chunk_tokens
        self.committed=''
        self.pending=[]

    def append(self,token):
        self.pending.append(token)
        tail=self.tokenizer.decode(self.pending,skip_special_tokens=False,clean_up_tokenization_spaces=False)
        text=self.committed+tail
        # Keep a partial byte sequence pending until a later token completes it.
        if len(self.pending)>=self.chunk_tokens and not tail.endswith('\ufffd'):
            self.committed=text
            self.pending=[]
        return text
