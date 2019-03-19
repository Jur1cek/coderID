import sys
import warnings
if not sys.warnoptions:
    warnings.simplefilter("ignore")
from cmd import Cmd
import sys
import pickle
import os
import zipfile
import string
import gitProfileSet
import ProfileSet
import testCommitClassification
import copy
import numpy as np
import csv
import Classifier
import PPTools
import heapq
from sklearn.ensemble import RandomForestClassifier
from sklearn.model_selection import cross_val_score,ShuffleSplit, StratifiedKFold
from sklearn import metrics, utils
from sklearn.metrics import classification_report

from plotting import plot_roc_auc_curves



from tqdm import tqdm

class MyPrompt(Cmd):

    #TODO: make more OO.
    #TODO: remove class variable access
    #TODO: move utils into PPTools
    #TODO: task queue-ify execution

    def do_init(self):
        """Initialize profile set. non-existent file will create new  args: filePath"""
        #os.environ["DYLD_LIBRARY_PATH"] = "/usr/local/Cellar/llvm/7.0.1/lib/"
        self.featuresDetected = False
            
        self.gpsList = list()
        self.saveLocation = os.getcwd()+"/savedSets/"
        self.resultLocation = os.getcwd()+"/classResults/"
        self.plotLocation = os.getcwd()+"/plots/"

        for direc in [self.saveLocation, self.resultLocation, self.plotLocation]:
            try:
                os.mkdir(direc)
                print("directory ", direc, " Created.")
            except FileExistsError:
                continue

        for fileName in os.listdir(self.saveLocation):
            self.gpsList.append(fileName)

        if len(self.gpsList) is not 0:
            self.do_load(self.gpsList[0])
        else:
            self.activegps = gitProfileSet.gitProfileSet("default")

        self.prompt = self.activegps.name+">"
        print("Current set: "+self.activegps.name)
        
        

    def do_save(self, filepath=''):
        """Saves active gps, overwriting given file. Also used to rename set."""
        
        workingName = self.activegps.name
            
        print("saving...")
        if(filepath is ''):
            if workingName is "default":
                print("Note: saving under default, this is not recommended. Type a new name or press ENTER to accept: ")
                newName = input()
            else:
                newName = workingName
        else:
            newName = filepath 

        self.activegps.name = newName
        self.save(self.activegps)
        if newName not in self.gpsList:
            self.gpsList.append(newName)
        
        print("Saved to "+newName)

    @staticmethod
    def save(gps):
        file = open(os.getcwd()+"/savedSets/"+gps.name, 'wb')
        pickler = pickle.Pickler(file, pickle.HIGHEST_PROTOCOL)
        pickler.dump(copy.deepcopy(gps))
        
    def do_load(self, args):
        """Switches currently active gps to one with given name. ***PROLLY SHOULD SAVE FIRST***"""
        if(args == ""):
            print("Error, must supply name of existing gps. Use 'new' to start a fresh one.")
        self.activegps = self.load(args)
        self.prompt = self.activegps.name+">"

    def load(self, gpsName):
        for gpsFile in self.gpsList:
            path, extension = os.path.splitext(gpsFile)
            fileName = path.split("/")[-1]
            if gpsName == fileName:
                return(self.loadGPSFromFile(gpsName))

    def loadGPSFromFile(self, fileName):
        file = open(os.getcwd()+"/savedSets/"+fileName, 'rb')
        return pickle.Unpickler(file).load() 

    def do_ls(self, args):
        """List all available profile sets"""
        for gpsFile in self.gpsList:
            if self.activegps.name == gpsFile:
                print(gpsFile+"*")
            else:
                print(gpsFile)
        
    def do_rm(self, args):
        """Removes a specified gps permanently. pass * to remove all."""

        for gpsFile in self.gpsList:
            if gpsFile == args:
                os.remove(self.saveLocation+gpsFile)
                self.gpsList.remove(gpsFile)
                break
            if args == "*":
                os.remove(self.saveLocation+gpsFile)

    def do_getMasterAuthorList(self, args):
        """writes all authors in all currently mined repos to args.csv"""
        authors = []
        for savedSet in os.listdir(self.saveLocation):
            gps = self.loadGPSFromFile(savedSet)
            for author in gps.authors.values():
                authors.append([author.name, author.email])
        
        
            with open(self.resultLocation+args+".csv", 'w+') as csvfile:
                writer = csv.writer(csvfile, delimiter=',',
                                quotechar='|', quoting=csv.QUOTE_MINIMAL)
                for author in authors:
                    writer.writerow(author)


    def do_getGPSForAuthor(self, args):
        try:
            author = self.activegps.authors[args] 
        except Exception:
            print("Author not found")

        self.save(author.getGPSofSelf())

    def do_getGPSForEmail(self, args):
        dev = object()
        dev.name = args.split("@")[0]
        dev.email = args

        tempAuthor = gitProfileSet.gitAuthor(dev)
        return tempAuthor.getGPSofSelf()

    def do_mineDirectory(self, directory):
        """Mine all repos in directory and save the output"""

        if not os.path.isdir(directory):
            print("Not a directory!")
            return

        for subdir in os.listdir(directory):
            if subdir not in self.gpsList:
                self.do_new(subdir)
                self.do_loadGit(directory+"/"+subdir)
                self.do_compile("")
            else:
                print("Skipping "+subdir+" as it is already found.")
        
    def do_quit(self, args):
        """quits the program WITHOUT SAVING"""
        print("Quitting.")
        raise SystemExit

    def do_multiClassTest(self, args):
        expName = self.activegps.name
       
        if len(args) > 0:
            expName = args[0]

        if not self.activegps.featuresDetected:
            print("Running Feature Detection")
            self.activegps.getFeatures()
            self.activegps.featuresSelected = None
            self.do_save()

        # if self.activegps.featuresSelected is None:
        #     self.activegps.featureSelect()
        #     self.do_save()

        print("Generating Class Report")
        splits = int(PPTools.Config.config["Cross Validation"]["n_splits"])
        cv = StratifiedKFold(n_splits=splits, shuffle=True)
        pred = []
        tar = []
        conf = []
        imp = None  #cumulative feature importances
        #print("Cross Validating")
        features = self.activegps.counts
        targets = self.activegps.target
        for train, test in cv.split(features, targets):

            trFeatures = features[train]
            trTarget = targets[train]   #grab the training set...

            teFeatures = features[test]
            teTarget = targets[test]    #...and the test set.

            conf = dict()
            for author in tqdm(self.activegps.authors.keys()):
                clf = Classifier.Classifier().model
                auth_trFeatures = self.reFeSe(clf, trFeatures, trTarget)    #feature select for the athor
                clf = self.train_binary(trFeatures[:,auth_trFeatures], trTarget, author)
                if clf.classes_[0] == author:   #Make sure the author in question is treated as the pos label...
                    conf[author] = [prob[0] for prob in clf.predict_proba(teFeatures[:,auth_trFeatures])]
                else:
                    conf[author] = [prob[1] for prob in clf.predict_proba(teFeatures[:,auth_trFeatures])]

            for i in range(0, len(teTarget)):
                max_prob = 0
                guess = ""
                for author in self.activegps.authors.keys():
                    prob = conf[author][i]
                    if prob > max_prob:
                        max_prob = prob
                        guess = author
                
                pred.append(guess)

            tar.extend(teTarget)

        
        print(classification_report(pred, tar, output_dict=False))
        report = classification_report(pred, tar, output_dict=True)
         

        with open(self.resultLocation+expName+"_multi_report.csv", 'w+') as reportFile:
            w = csv.writer(reportFile)
            oneReport = list(report.items())[0]     
            oneSample = oneReport[1]
            header = ["Author"]
            header.extend(oneSample.keys())
            #print(header)
            w.writerow(header)
            #make classification report
            for authorName, result in report.items():
                row = [authorName]+[value for key, value in result.items()]
                print(row)
                w.writerow(row)

        
     
    def binaryify(self, outputs, author):
        targets = []
        authorInd = []
        notAuthorInd = []
        for i in range(0,len(outputs)):  #find indeces containing examples from author in question
            authorName = outputs[i]
            if authorName == author:
                targets.append(author)
                authorInd.append(i)
            else:
                targets.append("not_"+author)
                notAuthorInd.append(i)

        return (np.array(targets), authorInd, notAuthorInd)

    def train_binary(self, features, outputs, author):
        
        targets, authorInd, notAuthorInd = self.binaryify(outputs, author)

        authorCount = len(authorInd)
        notAuthorCount = len(notAuthorInd)

        test_ratio = float(PPTools.Config.config['Cross Validation']['test_ratio'])

        if authorCount / notAuthorCount < test_ratio:  #if author makes up less than test_ratio of the sample, reduce the sample size
            maxNotAuthorAllowed = int((1 / test_ratio) * authorCount)
            from random import sample
            notAuthorInd = sample(notAuthorInd, maxNotAuthorAllowed)
            features = features[authorInd+notAuthorInd]
            targets = [targets[i] for i in authorInd+notAuthorInd]
        
        targets = np.array(targets)

        clf = Classifier.Classifier().model
        
        #cross validate for prec and rec
        clf.fit(features, targets)   #train the model
        return clf #return the model

    def reFeSe(self, model, features, targets):
         #train with all features to start

        previous = 0
        strength = .01
        previousBest = range(0, features.shape[1])
        best = None
        nFeatures = features.shape[1]

        retFeatures = features

        #reduce sample size to decrease training time
        maxSamples = int(PPTools.Config.config["Feature Selection"]["max_samples"])
        reductionFactor = float(PPTools.Config.config["Feature Selection"]["reduction_factor"])
        if len(targets) > maxSamples:
            from random import sample
            samples = sample(range(0,len(targets)), maxSamples)
            features = features[samples,:]
            targets = targets[samples]

        #choose optimal feature set size
        while True:
            previous = strength
            
            strength, importances = self.evaluate(model, features, targets)
            #print((nFeatures, strength))
            if strength < previous:
                break
            from operator import itemgetter
            match = zip(range(0, features.shape[1]), importances)            
            
            nFeatures = int((1-reductionFactor)*nFeatures)
            
            if best is not None:
                previousBest = best

            best = list(map(lambda x: x[0], heapq.nlargest(nFeatures, match, key = itemgetter(1))))

            features = features[:,best]

        return previousBest
        

    def evaluate(self, clf, features, targets):
        from sklearn.model_selection import cross_val_score, ShuffleSplit
        numSamples = features.shape[0]
        section = 'Cross Validation'

        splits = PPTools.Config.get_value(section, 'n_splits')
        trSize = int(min(PPTools.Config.get_value(section, 'train_min'),
                         numSamples * PPTools.Config.get_value(section, 'train_ratio')))
        teSize = int(min(PPTools.Config.get_value(section, 'test_min'),
                         numSamples * PPTools.Config.get_value(section, 'test_ratio')))
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


    def do_twoClassTest(self, args):
        """Builds and evaluates a Random Forest classifier over each author and write results to a file."""

        expName = self.activegps.name
       
        if len(args) > 0:
            expName = args[0]

        if not self.activegps.featuresDetected:
            print("Running Feature Detection")
            self.activegps.getFeatures()
            self.activegps.featuresSelected = None
            self.do_save()

        # if self.activegps.featuresSelected is None:
        #     self.activegps.featureSelect()
        #     self.do_save()

        print("Generating Class Report")

        results = dict()
        for authorName in tqdm(self.activegps.authors.keys()):
            results.update(
                {authorName:
                    self.twoClassTest(authorName, dictOutput=True)
                }
            )

        import csv

        # Create csv target directory if non-existent
        
        # imp = None
        # for authorName, result in results.items():
        #     importances = result["importances"]
        #     if imp is None:
        #         imp = importances
        #     else:
        #         imp = np.add(imp,importances)

        # best = self.bestNFeatures(imp, self.activegps.terms, 200)

        # #write best features
        # with open(self.resultLocation+expName+"_best_features.csv", 'w+') as csvfile:
        #     writer = csv.writer(csvfile, delimiter=',',
        #                     quotechar='|', quoting=csv.QUOTE_MINIMAL)

        #     for item in best:
        #         writer.writerow(item)

        with open(self.resultLocation+expName+"_binary_report.csv", 'w+') as reportFile:
            w = csv.writer(reportFile)
            oneReport = list(results.items())[0]
            oneSample = oneReport[1][oneReport[0]]
            header = ["Author"]
            header.extend(oneSample.keys())
            #print(header)
            w.writerow(header)
            #make classification report
            for authorName, result in results.items():
                result = result[authorName]
                row = [authorName]+[value for key, value in result.items()]
                print(row)
                w.writerow(row)

        # Plot ROC AUC curves
        plot_roc_auc_curves(results, self.plotLocation, expName)

    def twoClassTest(self, author, dictOutput=False):
        
        if author not in self.activegps.authors:
            print("Author not found")
            return
        gps = self.activegps
        if not gps.featuresDetected:
            print("Running Feature Detection")
            gps.getFeatures()
        
        
        targets = self.activegps.target
        features = self.activegps.counts

        targets = self.binaryify(targets, author)[0]   #make problem binary

        clf = Classifier.Classifier().model
        
        #cross validate for prec and rec
        splits = int(PPTools.Config.config["Cross Validation"]["n_splits"])
       
        cv = StratifiedKFold(n_splits=splits, shuffle=True)
        pred = []
        tar = []
        conf = []
        imp = None  #cumulative feature importances
        #print("Cross Validating")

        fSet = self.reFeSe(clf, features, targets)
        features = features[:,fSet]
        
        for train, test in cv.split(features, targets):

            trFeatures = features[train]
            trTarget = targets[train]   #grab the training set...

            clf = self.train_binary(trFeatures, trTarget, author)   #train the model

            teFeatures = features[test]
            teTarget = targets[test]    #...and the test set.

            if imp is None:
                imp = clf.feature_importances_  #grab the feature importances
            else:
                imp = np.add(imp, clf.feature_importances_)

            pred.extend(clf.predict(teFeatures))    #evaluate on the test data
            tar.extend(teTarget)

            if clf.classes_[0] == author:   #Make sure the author in question is treated as the pos label...
                conf.extend([prob[0] for prob in clf.predict_proba(teFeatures)])
            else:
                conf.extend([prob[1] for prob in clf.predict_proba(teFeatures)])

        imp = np.divide(imp,splits)

        from sklearn.metrics import auc, roc_curve  #AUC computation

        fpr, tpr, thresholds = roc_curve(tar, conf, pos_label=author)   #...for this
        auc = auc(fpr, tpr)

        report = classification_report(pred, tar, output_dict=dictOutput)
        #print(classification_report(pred, tar, output_dict=False))
        report[author]["AUC"] = auc
        report["importances"] = imp
        report["fpr"] = fpr
        report["tpr"] = tpr
        report["targets"] = list(map(lambda label: 1 if label == author else 0, tar))
        report["predictions"] = conf

        return report

    def do_featureDetect(self, args):
        """Perform feature selection operations. 
        This is called automatically from classifyFunctions if not run already.
        This resets the state of selected features, requiring that procedure to be run again."""   
        
        self.activegps.getFeatures()
        self.activegps.featuresSelected = None
        self.do_save()

    def do_multiOutputTest(self, args):
        expName = self.activegps.name
       
        if len(args) > 0:
            expName = args[0]

        if not self.activegps.featuresDetected:
            print("Running Feature Detection")
            self.activegps.getFeatures()
            self.activegps.featuresSelected = None
            self.do_save()

        print("Generating Class Report")
        splits = int(PPTools.Config.config["Cross Validation"]["n_splits"])
        cv = StratifiedKFold(n_splits=splits, shuffle=True)
        pred = []
        tar = []
        imp = []  #cumulative feature importances
        #print("Cross Validating")
        features = self.activegps.counts
        targets = self.activegps.target
        for train, test in tqdm(list(cv.split(features, targets))):

            trFeatures = features[train]
            trTarget = targets[train]   #grab the training set...

            teFeatures = features[test]
            teTarget = targets[test]    #...and the test set.

            #train multi-output classifier
            clf = Classifier.Classifier().model
            
            selectedFeatures = self.reFeSe(clf, trFeatures, trTarget)
            trFeatures = trFeatures[:,selectedFeatures]    #feature select for the athor
            
            clf.fit(trFeatures, trTarget)

            pred.extend(clf.predict(teFeatures[:,selectedFeatures]))
            tar.extend(teTarget)

        
        print(classification_report(pred, tar, output_dict=False))
        report = classification_report(pred, tar, output_dict=True)
         

        with open(self.resultLocation+expName+"_multi_report.csv", 'w+') as reportFile:
            w = csv.writer(reportFile)
            oneReport = list(report.items())[0]     
            oneSample = oneReport[1]
            header = ["Author"]
            header.extend(oneSample.keys())
            #print(header)
            w.writerow(header)
            #make classification report
            for authorName, result in report.items():
                row = [authorName]+[value for key, value in result.items()]
                print(row)
                w.writerow(row)



    def do_authorsInCommon(self, args):
        for file1 in os.listdir(self.saveLocation):
            for file2 in os.listdir(self.saveLocation):
                if file1 == file2:
                    break
                gps1 = self.loadGPSFromFile(file1)
                gps2 = self.loadGPSFromFile(file2)
                inCommon = self.authorsInCommon(gps1, gps2)
                
                if inCommon: #if not empty
                    print(file1+", "+file2+": "+str(inCommon))



    def authorsInCommon(self, gps1, gps2):
        return [author for author in gps1.authors.keys() if author in gps2.authors]
        

    def do_pruneGit(self, args):
        """Limit to N authors with between k and m functions. 0 for unlimited"""
        args = args.split(" ")
        if len(args) != 3:
            print("Requires 3 args")
            return

        n= int(args[0])
        k= int(args[1])
        m= int(args[2])
        
        print("Pruning Authors")
        old = self.activegps.authors

        new = dict()
        count = 0
        for item in tqdm(old.items()):
            #print(item)
            if len(item[1].functions) >= k and len(item[1].functions) <= m:
                new.update([item])
                count+=1
                if count == n and n != 0:
                    break

        self.activegps.authors = new
        self.activegps.featuresDetected = False

    def do_new(self, args):
        """Re-initializes profile set to be empty"""
        if args == "":
            print("No name given, initializing to \"default\"")
            self.activegps = gitProfileSet.gitProfileSet("default")
        else:
            self.activegps = gitProfileSet.gitProfileSet(args)
            self.gpsList.append(args)

        self.prompt = self.activegps.name+">"
             
    def do_loadGit(self, args):
        """Loads a single git repo. Can be local or remote."""
        if args =="":
            print("Must enter a path to a git repo.")
        for filePath in args.split(" "):
            self.activegps.addRepo(filePath)
        self.do_displayGitAuthors("")

    def do_displayGitAuthors(self, args):
        """Displays all authors found in the currently loaded git repos"""
        self.activegps.displayAuthors()
        #print(self.activegps)

    def do_loadGitRepos(self, args):
        """Loads a directory args[0] of git repos, as many as args[1] def:inf"""
        args = args.split(" ")
        if len(args) == 0:
            "Must enter a directory"
        
        if len(args)>1:
            lim = int(args[1])
        else:
            lim = float("inf")
        repos = ProfileSet.listdir_fullpath(args[0])
        for i in range(0,min(len(repos), lim)):
            if not os.path.basename(repos[i])[0]==".":
                self.do_loadGit(repos[i])

    def do_compile(self, args):
        """Mine the selected repos for relevant commits. Saves automatically upon completion, so if you want a name other than default save it first"""
        args = args.split(" ")
       # try:
        if len(args) > 1:
            self.activegps.compileAuthors(int(args[0]), int(args[1]) )
        else:
            self.activegps.compileAuthors()
        print("Compilation Complete")
        #except Exception:
         #   print("Problem during compilation. Saving...")
        
        self.do_save()
        
       
    def do_view(self, args):
        """View author[0]'s: n[1] most recent (commits, repos, files, functions, lines)[3]"""
        #TODO add quality directions
        try:
            args = args.split(":")
            author = self.activegps.authors.get(args[0])

            args = args[1].strip().split(" ")

            n = int(args[0])
            target = args[1]

            if target == "commits":
                target = author.commits.values()
            
            elif target == "repos":
                target = author.repos.values()

            elif target == "files":
                target = author.files

            elif target == "functions":
                total = 0

                for fun in author.functions:
                    ((hsh, fil, line),code) = next(iter(fun.items())) #Python is whack man.
                    print(fil+":")
                    for line in fun.values():
                        print(line)
                print()
                return
                
            elif target == "lines":
                target = author.lines.values()

            total =0

            for item in target:
                print(item)
                total+=1
                if total>n:
                    return

        except Exception as e:
            print(str(e))
            print("Hint: view Dan: 10 lines")
            return
    

    def do_getGitRepos(self,args):
        """WINDOWS ONLY Read repos from reporeapers .csv file, fetch and store in target directory, using temp if specified. Use temp if trying to download to external drive"""
        if args == "":
            print("Must supply a target filepath.")
            return
        args = args.split(" ")
        
        inputFile = args[0]
        import csv
        data = list(csv.reader(open(inputFile)))
        outputDir = args[1]
        if len(args)>2:
            tempdir = args[2]
        else:
            tempdir = None
        for row in data[1:]:
            repo = row[0]
            
            import subprocess
            import shutil 
            repoDirName = repo.split("/")[1]
            if tempdir != None:
                downTarget = tempdir
            else:
                downTarget = outputDir
            if os.path.exists(downTarget+"/"+repoDirName):
                continue
            if repoDirName not in os.listdir(outputDir):
                #TODO: Make linux worthy
                subprocess.Popen([r'C:/Windows/System32/WindowsPowerShell/v1.0/powershell.exe',
                    '-ExecutionPolicy',
                    'Unrestricted',
                    './downloadrepos.ps1',
                    str(repo), downTarget], cwd=os.getcwd()).wait()  
                if tempdir != None:
                    shutil.copytree(tempdir+repoDirName, outputDir+"/"+repoDirName)
                    shutil.rmtree(tempdir+repoDirName)

    @staticmethod
    def bestNFeatures(imp, names, n):
        match = dict(zip(names, imp))
        import operator
        sortedMatch = sorted(match.items(), key=operator.itemgetter(1), reverse=True)
        return sortedMatch[0:n]

    def do_gpsInfo(self, args):
        """print basic info about this gps"""
        print(self.activegps)

    def do_testCommitClassification(self, args):
        testCommitClassification.test_heuristic_function()

    
def memory_limit():
    import resource
    soft, hard = resource.getrlimit(resource.RLIMIT_AS)
    resource.setrlimit(resource.RLIMIT_AS, (get_memory() * 1024 , hard))

def get_memory():
    with open('/proc/meminfo', 'r') as mem:
        free_memory = 0
        for i in mem:
            sline = i.split()
            if str(sline[0]) in ('MemFree:', 'Buffers:', 'Cached:'):
                free_memory += int(sline[1])
    return free_memory

if __name__ == '__main__':
    
    #memory_limit() # Limitates maximun memory usage to 90%
    try:
        prompt = MyPrompt()
        prompt.prompt = 'coderID> '
        prompt.do_init()
        prompt.cmdloop('Starting prompt...')
    except MemoryError:
        sys.stderr.write('\n\nERROR: Memory Exception\n')
        sys.exit(1)
