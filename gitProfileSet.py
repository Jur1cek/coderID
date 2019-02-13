import os
import re
import time
import queue

import PPTools
import ASTFeatureExtractor
import pydriller
import featureExtractors
import multiprocessing
import sys
import warnings
if not sys.warnoptions:
    warnings.simplefilter("ignore")
import numpy as np
from collections import Counter
import itertools
from tqdm import tqdm
from scipy.sparse import hstack, vstack, csr_matrix
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.feature_selection import mutual_info_classif, SelectKBest


class gitProfileSet:

    #TODO: Make it so re-compiling doesn't break
    #TODO: Make sibling class of ProfileSet
    
    langList =["cpp", "c"]
    def __init__(self, name):
        """Initialize a new gitset"""
        self.name = name
        self.repos = []
        self.authors = dict()
        self.featuresDetected = False
        self.featuresSelected = None
        self.termsSelected = None
        self.minedRepos = set()

    def addRepo(self, args):
        print("Adding repo: "+args)
        try:
            if args not in self.repos:
                self.repos.append(args)
        except Exception:
            print("Couldn't get that one...")
        #self.compileAuthors(newRepo)    
          
    #TODO: take args from cli
    def compileAuthors(self, minAuth = 25, minDocs = 9):
        import sys
        platform = sys.platform
        self.compileInSequence(minAuth, minDocs)

    def compileInSequence(self, minAuthors, minDocs):
        
        authorsWithEnoughDocs = 0
        for author in self.authors:
            if len(author.functions) > minDocs:
                authorsWithEnoughDocs += 1

        for repo in self.repos:
            if authorsWithEnoughDocs >= minAuthors:
                return
            if repo in self.minedRepos:
                continue
            else:
                self.minedRepos.add(repo)
            miner = pydriller.repository_mining.RepositoryMining(repo, only_modifications_with_file_types=gitProfileSet.langList,only_no_merge=True)
            repository = pydriller.GitRepository(repo)
            print("Scanning repo: "+miner._path_to_repo)
            
            tipeCounts = dict()

            for commit in tqdm(miner.traverse_commits()):
                tipe = commitType.categorize(commit)

                if tipe not in tipeCounts:
                    tipeCounts.update({tipe: 0})
                count = tipeCounts.get(tipe)
                tipeCounts.update({tipe: count+1})


                if tipe is commitType.FEATURE:
                    author = commit.author
                    if author.name not in self.authors:
                        self.authors.update({author.name:gitAuthor(author)})
                        #print("Found new author: "+author.name)
                    
                    author = self.authors.get(author.name)

                    author.commits.add(repo + commit.hash)

                    if repo not in author.repos:
                        author.repos.add(repo)
                    
                    for mod in commit.modifications:
                        mod._calculate_metrics()
                        if mod.new_path is None or not mod.new_path.split(".")[-1] in gitProfileSet.langList:
                            continue
                        
                        author.files.add(mod.new_path)
                        #parse diff and add lines to list
                        
                        leDiff = repository.parse_diff(mod.diff)
                        for num, line in leDiff["added"]:
                            author.lines.update({(commit.hash,mod.new_path,num):line})

                        #extract functions with lizard
                        funs = mod._function_list

                        #maintain list of dicts containing the source code of specific functions. Same format as for lines
                        lineIndex = 0
                        for fun in funs:
                            newFun = dict()
                            try:
                                while(leDiff["added"][lineIndex][0]<fun.start_line):
                                    lineIndex+=1
                            
                                while(leDiff["added"][lineIndex][0]<fun.end_line+1):
                                    newFun.update({(commit.hash,mod.new_path,leDiff["added"][lineIndex][0]):leDiff["added"][lineIndex][1]})
                                    lineIndex+=1
                            except IndexError: #if end of input reached before end of functions. This is probable when non-complete functions are submitted.
                                pass
                            if len(newFun) > 1:
                                author.functions.append(newFun)
                                if len(author.functions) == minDocs:
                                    authorsWithEnoughDocs += 1
                                    

                    
                    
            print(str("finished"+str(miner._path_to_repo)))
            print("types: "+str(tipeCounts))
            #print(authorsWithEnoughDocs+" authors with enough code so far.")



    def displayAuthors(self):
        for value in self.authors.values():
            print(value)


    def getFeatures(self, numAuthors=-1):
        inputs=[]
        node_types = []
        code_unigrams = []
        self.target = []
        charfeatureNames = featureExtractors.featureExtractors.charfeatureNames
        charLevelFeatures = None
        tokfeatureNames = featureExtractors.featureExtractors.tokfeatureNames
        tokFeatures = None

        print("Gathering char and token level features") # generating tokens/unigrams
        authors_seen = 0
        for author in tqdm(self.authors.values()):
            if numAuthors != -1 and authors_seen == numAuthors:
                    break
            authors_seen += 1

            for fun in author.functions:
                fn_str = '\n'.join(fun.values())

                #whitespace fn's still getting in. This will catch for that.
                if fn_str.isspace() or fn_str == '':
                    continue

                try:
                    tu = PPTools.Tokenize.get_tu(fn_str)
                    tokens = list(tu.get_tokens(extent=tu.cursor.extent)) #Sometimes this  breaks for n.a.r.
                    inputs.append(PPTools.Tokenize.tokensToText(tokens))  # Convert to text

                    #Reset tu Brute?
                    #tu = PPTools.Tokenize.get_tu(fn_str)
                    
                    #tree = ASTFeatureExtractor.AST(tu.cursor)
                    #tree.traverse()

                    # TODO: concatenate in the featureExtractor module or here?
                    #node_types.append(" ".join(tree.node_types))
                    #code_unigrams.append(" ".join(tree.code_unigrams))
                    #del tree

                except Exception:
                    continue

                """
                Bigram matrix:
                Create a dok matrix (Dictionary Of Keys based sparse matrix) here
                """
                # Function-string level features
                if charLevelFeatures is None:
                    charLevelFeatures = featureExtractors.featureExtractors.characterLevel(fn_str)
                else:
                    charLevelFeatures = vstack([charLevelFeatures,
                                                featureExtractors.featureExtractors.characterLevel(fn_str)])


                # Token-level features
                # if tokFeatures is None:
                #     tokFeatures = featureExtractors.featureExtractors.tokenLevel(tokens)
                # else:
                #     tokFeatures = vstack([tokFeatures, featureExtractors.featureExtractors.tokenLevel(tokens)])

                self.target.append(author.name)
                del tokens
            
        inputs = np.array(inputs)

        # TODO: abstract this out since it gets used a lot.
        print("Vectorizing...")
        vectorizer =  TfidfVectorizer(analyzer="word", token_pattern="\S*",
                                       decode_error="ignore", lowercase=False)
        vectorizer_tf = TfidfVectorizer(analyzer="word", token_pattern="\S*",
                                        decode_error="ignore", lowercase=False,
                                        use_idf=False)

        self.counts = hstack([charLevelFeatures, tokFeatures], format = 'csr')
        self.terms = charfeatureNames #+ tokfeatureNames

        need_tf = False

        #i = 0
        #for features in tqdm([inputs, node_types, code_unigrams]):
        #    i += 1
            # TFIDF
        self.counts = hstack([self.counts, vectorizer.fit_transform(inputs)],
                                 format = 'csr')
        self.terms += vectorizer.get_feature_names()

            # Get only the term frequencies
        # if need_tf:
        #     self.counts = hstack([self.counts, vectorizer_tf.fit_transform(features)],
        #                             format = 'csr')
        #     self.terms += vectorizer_tf.get_feature_names()
        # else:
        #     # accounts for the fact that we do not need the TF of the unigrams/inputs
        #     need_tf = True

        del inputs, node_types, code_unigrams

        self.target = np.array(self.target)

        self.featuresDetected = True
            #should fit feature detector here
            #then pass it down

    def featureSelect(self, reductionFactor = .5):
        # First round feature selection using mutual information

        if self.featuresSelected is not None:
            print("Features selected already, skipping.")
        

        total_num_features = self.counts.shape[1]
        print("Number of features before selection: {}".format(total_num_features))

        from sklearn.ensemble import RandomForestClassifier
        from sklearn import feature_selection
        import heapq
        
        #featureSets = dict() #keep track of sets and feature importances
        #format: key=n_features value = (strength, features, importances)

        clf = RandomForestClassifier(n_estimators=300, oob_score=True, max_features="sqrt")
        
        #train with all features to start

        previous = 0
        strength = .01
        
        #entry = {total_num_features:(strength, self.counts, importances)}  #make first entry
        
        nFeatures = total_num_features
        features = self.counts
        terms = self.terms
        
        previousFeatures = None
        previousTerms = None

        #choose optimal feature set size
        while strength > previous:
            previous = strength
            
            strength, importances = self.evaluate(clf, features, self.target)
            print((nFeatures, strength))

            from operator import itemgetter
            match = zip(range(0, nFeatures), importances)            
            
            nFeatures = int(reductionFactor*nFeatures)
            
            previousFeatures = features
            previousTerms = terms

            best = list(map(lambda x: x[0], heapq.nlargest(nFeatures, match, key = itemgetter(1))))

            features = features[:,best]
            terms = [terms[i] for i in best]

        self.featuresSelected = previousFeatures
        self.termsSelected = previousTerms               
        
        #selector = RFECV(clf, cv=cv, step = int(total_num_features/10), min_features_to_select=1000, verbose = 3, n_jobs=1)
        #selector.fit(self.counts, self.target)

        print("Features selected...")

        #self.counts = features
        #self.termsSelected = [self.terms[i] for i in self.selectedFeatures]

        n_relevant_features = len(self.termsSelected)

        print("Number of features after selection: {}".format(n_relevant_features))
        frac_selected = 100 * n_relevant_features / total_num_features
        print("Percentage of features selected: {:.2f}%".format(frac_selected))

    def evaluate(self, clf, features, targets, splits =3):
        from sklearn.model_selection import cross_val_score, ShuffleSplit
        numSamples = features.shape[0]
        
        trSize = int(min(1000 ,  numSamples* .5))
        teSize = int(min(200 , numSamples* .2))
        featureCount = features.shape[1]
        cv = ShuffleSplit(n_splits=splits, train_size=trSize, test_size=teSize)
        
        
        importances = np.zeros(featureCount)
        strength = 0
        for train, test in cv.split(features, targets):

            trFeatures = features[train]
            trTarget = targets[train]

            teFeatures = features[test]
            teTarget = targets[test]
   
            clf.fit(trFeatures, trTarget)

            predictions = clf.predict(teFeatures)

            stren = len(np.where(predictions == teTarget)[0])/teSize

            strength += stren / splits
            importances += clf.feature_importances_ / splits
            

        return (strength, importances)
        

    def plotLearningCurve(self, clf, features, targets):
        """display performance as a function of feature set size"""

        
    def functionToString(self, lines):
        textLines = list(len(lines))

        for lineInfo, line in lines:
            cHash, fil, lnum = lineInfo
            textLines[lnum] = line

        return "\n".join(textLines)

    
    def __str__(self):
         return (str(len(self.authors))+" authors. "+str(sum(map(lambda x: len(x.functions), self.authors.values())))+" functions in total.")

        
        

class gitAuthor:

    def __init__(self, dev):
        if dev is not None:
            self.name = dev.name
            self.email = dev.email
        self.commits = set() #store with repo+commitHash
        self.files = set()
        self.functions = list() #list of dicts. Each dict represents a function. str same as self.lines 
        self.lines = dict() #key: {commitHash,file.cpp,lineNumber} value: literal code
        self.repos = set()
    
    def merge(self, other):
        """merges the authors into one author object, keeping self.name"""
        print("Merging author: "+self.name)
        self.commits.update(other.commits)
        self.functions.extend(other.functions)
        self.files.union(other.files)
        self.lines.update(other.lines)
        
    def __str__(self):
        return self.name+": "+str(len(self.commits))+" commits. "+str(len(self.lines))+" LOC, "+str(len(self.functions))+" complete functions from "+str(len(self.repos))+ " repos."
    
from enum import Enum     
class commitType(Enum):
    FEATURE = "FC"
    BUGFIX = "BF"
    REFACTOR = "RF"
    OTHER = "OTH"

    types = {FEATURE, BUGFIX, REFACTOR, OTHER}

    def describe(self):
        # self is the member here
        return self.name, self.value
    
    #TODO: User better heuristic
    @staticmethod
    def categorize(commit):
        added= 0
        removed =0
        for mod in commit.modifications:
            if mod.new_path is None or not mod.new_path.split(".")[-1] in gitProfileSet.langList:
                continue
            #mod._calculate_metrics()
            added += mod.added
            removed += mod.removed

        if added == 0:
            return commitType.OTHER
        
        if added-removed < .1*added:
            if added < 20:
                return commitType.BUGFIX
            else:
                return commitType.REFACTOR        
        
        if added > 20:
            return commitType.FEATURE

        return commitType.OTHER



        