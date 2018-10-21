import os.path
import pickle
import FeatureSet
import PPTools
from os import walk

class ProfileSet:
    
    def __init__(self, file, lang="cpp", config=None):
        self.fileSource = file
        self.cfg = config
        self.language = lang
        if os.path.isfile(file):
            self.merge(pickle.Unpickler(file).load)
        else:
            self.authors = dict()

    def addAuthorsDir(self, topDir):
        for dir in os.listdir(topDir):
            self.addAuthor(dir)

    def merge(self, otherPS):
        self.authors = self.authors+otherPS.authors

    def addAuthor(self, dir):
        nAuth = Author(dir,self.cfg, self.language)
        if len(nAuth.docs)==0:
            print("No docs of type "+self.language+" found in "+dir)
            return
        if os.path.basename not in self.authors:
            self.authors.update(os.path.basename(dir),nAuth)
        else:
            self.authors.get(dir).merge(nAuth)
        


    def detectFeatures(self):
        for author in self.authors:
            author.collectForAllDocs()

    def toFeatureMatrix(self):
        target = []
        targetNum=0
        mat = []
        for author in self.authors :
            mat.append(author.featureMatrix())
            for _ in range(len(author.docs)):
                target.append(targetNum)
            targetNum+=1
        
        return mat, target

    def __str__(self):
        if self.cfg==None:
            return str(PPTools.Default.featureSet.keys).replace(",","\n")
        else:
            return str(FeatureSet.FeatureSet(self.cfg)).replace(",","\n")
            

    

class Author:
    def __init__(self, dir, cfg=None, lang="cpp"):
        self.authName = os.path.basename(dir)
        self.docs = []
        self.cfg=cfg
        self.language = lang
        for root, dirs, files in os.walk(".", topdown=False):
            for name in files:
                if lang in name:
                    self.docs.append(Document(os.path.join(root, name), cfg))
        #print("Assembling profile for author "+authName)

    def addDoc(self, file):
        self.docs.append(Document(file, self.cfg))
    
    def merge(self, other):
        self.docs.append(other.docs)

    def collectForAllDocs(self):
        for doc in self.docs:
            doc.collect

    def featureMatrix(self):
        featureMat = []
        for i in range(1, len(self.docs)):
            featureMat [i] = self.docs[i].getFeatureVector()
        return featureMat

    def __str__(self):
        toRet = self.authName+":\n"
        for doc in self.docs:
            toRet += "\t"+doc.name+"\n"
        return toRet


class Document:
    def __init__(self, file, cfg=None):
        self.name = os.path.basename(file)
        self.fileSource = file
        self.featureSet = FeatureSet.FeatureSet(cfg)

    def collect(self):
        self.featureSet.evaluate(self.fileSource)

    def featureVector(self):
        self.featureSet.getFeatureVector()
    
    


  
